from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException

from app.models.schemas import (
    AdaptationRequest,
    AdaptationResponse,
    BusinessConfig,
    BusinessConfigResponse,
    EvaluationRequest,
    EvaluationResponse,
    FullSystemRequest,
    FullSystemResponse,
    LegacyStrategyCompareRequest,
    LegacyStrategyCompareResponse,
    LoginRequest,
    LoginResponse,
    NetworkConfig,
    NetworkConfigResponse,
    OrchestrationRequest,
    OrchestrationResponse,
    PerformanceEvaluateRequest,
    PerformanceEvaluateResponse,
    ResourceAllocationRequestV2,
    ResourceAllocationResponseV2,
    SemanticProcessRequest,
    SemanticProcessResponse,
    SliceBuildRequest,
    SliceBuildResponse,
    SliceConfigRequest,
    SliceConfigResponse,
    UserBusinessItem,
    WorkflowRequest,
    WorkflowResponse,
)
from app.services.adaptation_service import adapt_users_to_slices
from app.services.auth_service import (
    ensure_role,
    extract_token_from_header,
    get_auth_stats,
    get_current_user,
    login,
    logout,
)
from app.services.evaluation_service import evaluate, evaluate_performance
from app.services.legacy_adapter import compare_legacy_strategies
from app.services.orchestration_service import allocate_user_resources, orchestrate_resources
from app.services.semantic_service import DEFAULT_TARGET_SNR_DB, build_business_config, build_network_config, process_services
from app.services.slicing_service import build_and_distribute, build_slice_config
from app.store.repository import (
    active_network_response,
    active_slice_response,
    build_state_snapshot,
    create_task_submission,
    create_workflow_run,
    get_business_output_for_submission,
    get_latest_submission_id,
    get_strategy_compare_summary,
    get_submission_task_items,
    persist_run_results,
    save_network_config,
    save_slice_config,
    save_strategy_compare_summary,
    complete_workflow_run,
    update_task_submission_status,
)
from app.store.state import STATE


router = APIRouter()

CURRENT_RUNTIME = {"allocation_algorithm": "semslice"}
STRATEGY_KEYS = ("semslice", "netslice", "noslice")
STRATEGY_NAME_MAP = {
    "semslice": "语义切片（PSO 20粒子/50迭代）",
    "netslice": "网络切片（随机模型+PSO 20粒子/50迭代）",
    "noslice": "无切片（随机模型+目标SNR均分）",
}
TARGET_SNR_POINTS = [-6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0]


def _model_to_dict(model):
    if model is None:
        return None
    if isinstance(model, dict):
        return {key: _model_to_dict(value) for key, value in model.items()}
    if isinstance(model, list):
        return [_model_to_dict(item) for item in model]
    if isinstance(model, (str, int, float, bool)):
        return model
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    return model


def _normalize_allocation_algorithm(raw: str) -> str:
    value = str(raw or "semslice").strip().lower()
    alias = {
        "pso": "semslice",
        "semantic": "semslice",
        "semantic_slice": "semslice",
        "weighted": "netslice",
        "latency_first": "netslice",
        "equal": "noslice",
        "random": "noslice",
        "no_slice": "noslice",
    }
    normalized = alias.get(value, value)
    if normalized not in STRATEGY_KEYS:
        raise HTTPException(status_code=400, detail="无效运行策略，仅支持 semslice/netslice/noslice")
    return normalized


def _resolve_adaptation_method(raw_method: str, allocation_algorithm: str) -> str:
    _ = raw_method
    strategy = _normalize_allocation_algorithm(allocation_algorithm)
    if strategy == "netslice":
        return "netslice"
    if strategy == "noslice":
        return "noslice"
    return "vocab"


def _ensure_runtime_configs() -> Tuple[int, NetworkConfig, NetworkConfigResponse, int, SliceConfigRequest, SliceConfigResponse]:
    network_pack = active_network_response()
    slice_pack = active_slice_response()
    if network_pack is None or slice_pack is None:
        raise HTTPException(status_code=409, detail="管理员尚未下发网络与切片配置，当前不可运行任务")
    network_id, network_config, network_output = network_pack
    slice_id, slice_request, slice_output = slice_pack
    return network_id, network_config, network_output, slice_id, slice_request, slice_output


def _task_item_map(submission_id: int) -> Dict[str, int]:
    return {str(row["biz_user_code"]): int(row["id"]) for row in get_submission_task_items(submission_id)}


def _build_strategy_response(
    business_output: BusinessConfigResponse,
    network_output: NetworkConfigResponse,
    slicing_output: SliceConfigResponse,
    network_config: NetworkConfig,
    adaptation_method: str,
    strategy: str,
) -> FullSystemResponse:
    resolved_method = _resolve_adaptation_method(adaptation_method, strategy)
    adaptation_output = adapt_users_to_slices(
        AdaptationRequest(users=business_output.users, slices=slicing_output.slices, method=resolved_method)
    )
    allocation_output = allocate_user_resources(
        ResourceAllocationRequestV2(
            users=business_output.users,
            relations=adaptation_output.relations,
            network=network_config,
            algorithm=strategy,
        )
    )
    performance_output = evaluate_performance(
        PerformanceEvaluateRequest(
            users=business_output.users,
            allocations=allocation_output.allocations,
            network=network_config,
            relations=adaptation_output.relations,
            allocation_algorithm=strategy,
        )
    )
    return FullSystemResponse(
        business_output=business_output,
        network_output=network_output,
        slicing_output=slicing_output,
        adaptation_output=adaptation_output,
        allocation_output=allocation_output,
        performance_output=performance_output,
    )


def _run_submission(
    submission_id: int,
    business_output: BusinessConfigResponse,
    network_config_id: int,
    slice_config_id: int,
    network_output: NetworkConfigResponse,
    slicing_output: SliceConfigResponse,
    network_config: NetworkConfig,
    adaptation_method: str,
    selected_strategy: str,
) -> FullSystemResponse:
    update_task_submission_status(submission_id, "running")
    task_map = _task_item_map(submission_id)
    selected = _normalize_allocation_algorithm(selected_strategy)
    selected_response: Optional[FullSystemResponse] = None

    for strategy in STRATEGY_KEYS:
        response = _build_strategy_response(
            business_output=business_output,
            network_output=network_output,
            slicing_output=slicing_output,
            network_config=network_config,
            adaptation_method=adaptation_method,
            strategy=strategy,
        )
        run_id = create_workflow_run(
            submission_id=submission_id,
            network_config_id=network_config_id,
            slice_config_id=slice_config_id,
            allocation_algorithm=strategy,
            adaptation_method=_resolve_adaptation_method(adaptation_method, strategy),
        )
        persist_run_results(
            run_id=run_id,
            task_item_map=task_map,
            adaptation_output=response.adaptation_output,
            allocation_output=response.allocation_output,
            performance_output=response.performance_output,
        )
        complete_workflow_run(run_id, response.performance_output)
        save_strategy_compare_summary(submission_id, strategy, response.performance_output)
        if strategy == selected:
            selected_response = response

    update_task_submission_status(submission_id, "completed")
    if selected_response is None:
        raise HTTPException(status_code=500, detail="运行结果生成失败")
    return selected_response


def _create_submission_and_run(
    owner_user_id: int,
    business_output: BusinessConfigResponse,
    network_config_id: int,
    slice_config_id: int,
    network_output: NetworkConfigResponse,
    slicing_output: SliceConfigResponse,
    network_config: NetworkConfig,
    adaptation_method: str,
    selected_strategy: str,
) -> FullSystemResponse:
    submission_id, _ = create_task_submission(owner_user_id, business_output)
    return _run_submission(
        submission_id=submission_id,
        business_output=business_output,
        network_config_id=network_config_id,
        slice_config_id=slice_config_id,
        network_output=network_output,
        slicing_output=slicing_output,
        network_config=network_config,
        adaptation_method=adaptation_method,
        selected_strategy=selected_strategy,
    )


@router.get("/state")
def get_state(user: Dict[str, object] = Depends(get_current_user)) -> dict:
    owner_user_id = None if user.get("role") == "admin" else int(user["user_id"])
    snapshot = build_state_snapshot(CURRENT_RUNTIME["allocation_algorithm"], owner_user_id)
    return _model_to_dict(snapshot)


@router.get("/system/config/status")
def get_system_config_status(user: Dict[str, object] = Depends(get_current_user)) -> dict:
    _ = user
    network_ready = active_network_response() is not None
    slicing_ready = active_slice_response() is not None
    return {
        "network_configured": network_ready,
        "slicing_configured": slicing_ready,
        "admin_config_ready": network_ready and slicing_ready,
        "allocation_algorithm": CURRENT_RUNTIME["allocation_algorithm"],
    }


@router.post("/auth/login", response_model=LoginResponse)
def auth_login(payload: LoginRequest) -> LoginResponse:
    return login(payload)


@router.post("/auth/logout")
def auth_logout(authorization: str = Header(None)) -> dict:
    token = extract_token_from_header(authorization)
    logout(token)
    return {"success": True}


@router.get("/auth/me")
def auth_me(user: Dict[str, object] = Depends(get_current_user)) -> dict:
    return user


@router.get("/auth/stats")
def auth_stats(user: Dict[str, object] = Depends(get_current_user)) -> dict:
    _ = user
    return get_auth_stats()


@router.get("/workflow/example")
def get_workflow_example() -> dict:
    return {
        "business": {
            "user_count": 6,
            "modality": "text",
            "default_requirement_type": "high_fidelity",
            "default_domain_type": "generic",
        },
        "network": {
            "total_bandwidth": 2.0,
            "total_power": 1.0,
            "target_snr_db": DEFAULT_TARGET_SNR_DB,
            "node_count": 5,
            "base_station_count": 1,
        },
        "slicing": {
            "slice_count": 3,
            "slice_names": ["slice-en", "slice-en90", "slice-en80"],
            "codec_count": 3,
            "codec_modality": "text",
            "knowledge_bases": [
                {"kb_id": "kb-vocab-en", "kb_type": "vocab_en", "knowledge_level": 1.0},
                {"kb_id": "kb-vocab-en90", "kb_type": "vocab_en90", "knowledge_level": 0.9},
                {"kb_id": "kb-vocab-en80", "kb_type": "vocab_en80", "knowledge_level": 0.8},
            ],
        },
        "adaptation_method": "vocab",
        "allocation_algorithm": "semslice",
    }


@router.post("/module/business/config", response_model=BusinessConfigResponse)
def module_business_config(payload: BusinessConfig, user: Dict[str, object] = Depends(get_current_user)) -> BusinessConfigResponse:
    _ = user
    return build_business_config(payload)


@router.post("/module/network/config", response_model=NetworkConfigResponse)
def module_network_config(payload: NetworkConfig, user: Dict[str, object] = Depends(get_current_user)) -> NetworkConfigResponse:
    ensure_role(user, ["admin"])
    output = build_network_config(payload)
    save_network_config(payload, int(user["user_id"]))
    return output


@router.post("/module/slice/config", response_model=SliceConfigResponse)
def module_slice_config(payload: SliceConfigRequest, user: Dict[str, object] = Depends(get_current_user)) -> SliceConfigResponse:
    ensure_role(user, ["admin"])
    output = build_slice_config(payload)
    save_slice_config(payload, int(user["user_id"]))
    return output


@router.post("/system/admin/runtime-policy")
def system_admin_runtime_policy(payload: dict, user: Dict[str, object] = Depends(get_current_user)) -> dict:
    ensure_role(user, ["admin"])
    CURRENT_RUNTIME["allocation_algorithm"] = _normalize_allocation_algorithm(payload.get("allocation_algorithm", "semslice"))
    return {"success": True, "allocation_algorithm": CURRENT_RUNTIME["allocation_algorithm"]}


@router.post("/system/admin/runtime-policy/recompute-current", response_model=FullSystemResponse)
def system_admin_runtime_policy_recompute_current(
    payload: dict,
    user: Dict[str, object] = Depends(get_current_user),
) -> FullSystemResponse:
    ensure_role(user, ["admin"])
    submission_id = get_latest_submission_id()
    if submission_id is None:
        raise HTTPException(status_code=400, detail="当前没有可重算的任务，请先提交任务")

    network_config_id, network_config, network_output, slice_config_id, _, slicing_output = _ensure_runtime_configs()
    business_output = get_business_output_for_submission(submission_id)
    selected_strategy = _normalize_allocation_algorithm(CURRENT_RUNTIME["allocation_algorithm"])
    adaptation_method = str(payload.get("adaptation_method", "similarity"))
    return _run_submission(
        submission_id=submission_id,
        business_output=business_output,
        network_config_id=network_config_id,
        slice_config_id=slice_config_id,
        network_output=network_output,
        slicing_output=slicing_output,
        network_config=network_config,
        adaptation_method=adaptation_method,
        selected_strategy=selected_strategy,
    )


@router.post("/module/adaptation", response_model=AdaptationResponse)
def module_adaptation(payload: AdaptationRequest, user: Dict[str, object] = Depends(get_current_user)) -> AdaptationResponse:
    _ = user
    return adapt_users_to_slices(payload)


@router.post("/module/resources/allocate", response_model=ResourceAllocationResponseV2)
def module_resources_allocate(
    payload: ResourceAllocationRequestV2,
    user: Dict[str, object] = Depends(get_current_user),
) -> ResourceAllocationResponseV2:
    _ = user
    return allocate_user_resources(payload)


@router.post("/module/performance/evaluate", response_model=PerformanceEvaluateResponse)
def module_performance_evaluate(
    payload: PerformanceEvaluateRequest,
    user: Dict[str, object] = Depends(get_current_user),
) -> PerformanceEvaluateResponse:
    _ = user
    return evaluate_performance(payload)


@router.post("/system/admin/run", response_model=FullSystemResponse)
def system_admin_run(payload: FullSystemRequest, user: Dict[str, object] = Depends(get_current_user)) -> FullSystemResponse:
    ensure_role(user, ["admin"])
    business_output = build_business_config(payload.business)
    network_output = build_network_config(payload.network)
    slicing_output = build_slice_config(payload.slicing)

    network_config_id = save_network_config(payload.network, int(user["user_id"]))
    slice_config_id = save_slice_config(payload.slicing, int(user["user_id"]))
    CURRENT_RUNTIME["allocation_algorithm"] = _normalize_allocation_algorithm(payload.allocation_algorithm)

    return _create_submission_and_run(
        owner_user_id=int(user["user_id"]),
        business_output=business_output,
        network_config_id=network_config_id,
        slice_config_id=slice_config_id,
        network_output=network_output,
        slicing_output=slicing_output,
        network_config=payload.network,
        adaptation_method=payload.adaptation_method,
        selected_strategy=CURRENT_RUNTIME["allocation_algorithm"],
    )


@router.post("/system/admin/run-submitted", response_model=FullSystemResponse)
def system_admin_run_submitted(payload: dict, user: Dict[str, object] = Depends(get_current_user)) -> FullSystemResponse:
    ensure_role(user, ["admin"])
    submission_id = get_latest_submission_id()
    if submission_id is None:
        raise HTTPException(status_code=400, detail="当前没有待运行任务")
    network_config_id, network_config, network_output, slice_config_id, _, slicing_output = _ensure_runtime_configs()
    business_output = get_business_output_for_submission(submission_id)
    selected_strategy = _normalize_allocation_algorithm(
        payload.get("allocation_algorithm", CURRENT_RUNTIME["allocation_algorithm"])
    )
    CURRENT_RUNTIME["allocation_algorithm"] = selected_strategy
    return _run_submission(
        submission_id=submission_id,
        business_output=business_output,
        network_config_id=network_config_id,
        slice_config_id=slice_config_id,
        network_output=network_output,
        slicing_output=slicing_output,
        network_config=network_config,
        adaptation_method=str(payload.get("adaptation_method", "similarity")),
        selected_strategy=selected_strategy,
    )


@router.post("/system/admin/compare-strategies-current")
def system_admin_compare_strategies_current(payload: dict, user: Dict[str, object] = Depends(get_current_user)) -> dict:
    _ = payload
    ensure_role(user, ["admin"])
    submission_id = get_latest_submission_id()
    if submission_id is None:
        raise HTTPException(status_code=400, detail="当前没有可对比的数据")
    comparisons = get_strategy_compare_summary(submission_id)
    if not comparisons:
        raise HTTPException(status_code=409, detail="策略缓存不完整，请先提交任务或重新下发配置触发重算")
    return {
        "task_count": max(int(item.get("task_count", 0)) for item in comparisons) if comparisons else 0,
        "metrics": ["avg_delay_ms", "avg_ss", "avg_s_se"],
        "comparisons": [
            {
                "strategy": item["strategy"],
                "strategy_name": STRATEGY_NAME_MAP.get(str(item["strategy"]), str(item["strategy"])),
                "avg_delay_ms": float(item["avg_delay_ms"]),
                "avg_ss": float(item["avg_ss"]),
                "avg_s_se": float(item["avg_s_se"]),
            }
            for item in comparisons
        ],
    }


@router.post("/system/admin/ss-snr-sweep")
def system_admin_ss_snr_sweep(payload: dict, user: Dict[str, object] = Depends(get_current_user)) -> dict:
    ensure_role(user, ["admin"])
    submission_id = get_latest_submission_id()
    if submission_id is None:
        raise HTTPException(status_code=400, detail="当前没有可用于曲线分析的任务数据，请先提交并运行任务")

    _, active_network, _, _, _, slicing_output = _ensure_runtime_configs()
    business_output = get_business_output_for_submission(submission_id)
    adaptation_method = str(payload.get("adaptation_method", "similarity"))

    points: List[dict] = []
    for snr_point in TARGET_SNR_POINTS:
        scenario_network = NetworkConfig(
            total_bandwidth=active_network.total_bandwidth,
            total_power=active_network.total_power,
            target_snr_db=snr_point,
            node_count=active_network.node_count,
            base_station_count=active_network.base_station_count,
        )
        row = {"snr_db": snr_point}
        for strategy_key in STRATEGY_KEYS:
            response = _build_strategy_response(
                business_output=business_output,
                network_output=build_network_config(scenario_network),
                slicing_output=slicing_output,
                network_config=scenario_network,
                adaptation_method=adaptation_method,
                strategy=strategy_key,
            )
            user_metrics = response.performance_output.user_metrics or []
            hf_values = [
                float(item.get("fidelity", 0.0))
                for item in user_metrics
                if str(item.get("requirement_type", "")) != "low_latency"
            ]
            rt_values = [
                float(item.get("fidelity", 0.0))
                for item in user_metrics
                if str(item.get("requirement_type", "")) == "low_latency"
            ]
            row[f"{strategy_key}_hf"] = float(sum(hf_values) / len(hf_values)) if hf_values else 0.0
            row[f"{strategy_key}_rt"] = float(sum(rt_values) / len(rt_values)) if rt_values else 0.0
        points.append(row)

    return {"task_count": len(business_output.users), "points": points}


def _submit_user_business(
    business_payload: BusinessConfig,
    user: Dict[str, object],
    adaptation_method: str = "similarity",
    selected_strategy: Optional[str] = None,
) -> dict:
    network_config_id, network_config, network_output, slice_config_id, _, slicing_output = _ensure_runtime_configs()
    business_output = build_business_config(business_payload)
    strategy = _normalize_allocation_algorithm(selected_strategy or CURRENT_RUNTIME["allocation_algorithm"])
    result = _create_submission_and_run(
        owner_user_id=int(user["user_id"]),
        business_output=business_output,
        network_config_id=network_config_id,
        slice_config_id=slice_config_id,
        network_output=network_output,
        slicing_output=slicing_output,
        network_config=network_config,
        adaptation_method=adaptation_method,
        selected_strategy=strategy,
    )
    return {
        "success": True,
        "submitted_count": len(business_output.users),
        "auto_run": True,
        "allocation_algorithm": strategy,
        "pending_total": 0,
        "core_metrics": _model_to_dict(result.performance_output.core_metrics),
        "run_result": _model_to_dict(result),
    }


@router.post("/system/user/submit")
@router.post("/system/tenant/submit")
def system_user_submit(payload: BusinessConfig, user: Dict[str, object] = Depends(get_current_user)) -> dict:
    ensure_role(user, ["user", "admin"])
    return _submit_user_business(payload, user, adaptation_method="similarity")


@router.post("/system/user/run", response_model=FullSystemResponse)
@router.post("/system/tenant/run", response_model=FullSystemResponse)
def system_user_run(payload: FullSystemRequest, user: Dict[str, object] = Depends(get_current_user)) -> FullSystemResponse:
    ensure_role(user, ["user", "admin"])
    result = _submit_user_business(
        payload.business,
        user,
        adaptation_method=payload.adaptation_method,
        selected_strategy=CURRENT_RUNTIME["allocation_algorithm"] if user.get("role") == "user" else payload.allocation_algorithm,
    )
    return FullSystemResponse(**result["run_result"])


@router.post("/semantic/process", response_model=SemanticProcessResponse)
def semantic_process(payload: SemanticProcessRequest) -> SemanticProcessResponse:
    return process_services(payload.services, payload.noise_dbm)


@router.post("/slices/build-distribute", response_model=SliceBuildResponse)
def slices_build(payload: SliceBuildRequest) -> SliceBuildResponse:
    return build_and_distribute(payload.services, payload.strategy)


@router.post("/workflow/run", response_model=WorkflowResponse)
def workflow_run(payload: WorkflowRequest) -> WorkflowResponse:
    semantic_output = process_services(payload.services, noise_dbm=-114.45)
    slicing_output = build_and_distribute(payload.services, payload.strategy)
    orchestration_output = orchestrate_resources(
        payload.services,
        slicing_output.slices,
        payload.network_state,
    )
    evaluation_output = evaluate(
        payload.services,
        semantic_output.items,
        slicing_output.assignment,
        orchestration_output.allocations,
    )

    response = WorkflowResponse(
        semantic=semantic_output,
        slicing=slicing_output,
        orchestration=orchestration_output,
        evaluation=evaluation_output,
    )
    STATE.last_run = response
    return response


@router.post("/analysis/legacy/strategy-compare", response_model=LegacyStrategyCompareResponse)
def analysis_legacy_strategy_compare(
    payload: LegacyStrategyCompareRequest,
    user: Dict[str, object] = Depends(get_current_user),
) -> LegacyStrategyCompareResponse:
    _ = user
    return LegacyStrategyCompareResponse(**compare_legacy_strategies(payload.scenario, payload.resource_vector))
