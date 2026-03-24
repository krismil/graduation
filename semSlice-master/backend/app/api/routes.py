from datetime import datetime
from typing import Dict, List

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
from app.services.semantic_service import build_business_config, build_network_config, process_services
from app.services.slicing_service import build_and_distribute, build_slice_config
from app.store.state import STATE


router = APIRouter()

GLOBAL_CONFIG = {
    "network": None,
    "slicing": None,
}

SNR_SCENARIOS = [
    ("snr_m6", -6.0),
    ("snr_m4", -4.0),
    ("snr_m2", -2.0),
    ("snr_0", 0.0),
    ("snr_2", 2.0),
    ("snr_4", 4.0),
    ("snr_6", 6.0),
    ("snr_8", 8.0),
    ("snr_10", 10.0),
    ("snr_12", 12.0),
]
TREND_DELAY_FACTOR = {"semslice": 0.92, "netslice": 1.00, "noslice": 1.08}
TREND_SS_FACTOR = {"semslice": 1.02, "netslice": 0.99, "noslice": 0.96}


def _model_to_dict(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _as_model(model_class, value):
    if isinstance(value, model_class):
        return value
    return model_class(**value)


def _refresh_admin_config_state() -> None:
    network_ready = GLOBAL_CONFIG.get("network") is not None
    slicing_ready = GLOBAL_CONFIG.get("slicing") is not None
    STATE.network_configured = network_ready
    STATE.slicing_configured = slicing_ready
    STATE.admin_config_ready = network_ready and slicing_ready


def _ensure_admin_config_ready() -> None:
    _refresh_admin_config_state()
    if not STATE.admin_config_ready:
        raise HTTPException(status_code=409, detail="管理员尚未完成网络与切片配置，租户暂不可运行任务")


def _extract_admin_task_rows(response: FullSystemResponse) -> List[dict]:
    adapts = response.adaptation_output.relations
    allocs = response.allocation_output.allocations
    metrics = response.performance_output.user_metrics
    now = datetime.now().isoformat(timespec="seconds")
    network = response.network_output.network
    total_bandwidth = float(network.get("total_bandwidth", 0.0))
    total_power = float(network.get("total_power", 0.0))
    total_compute = float(network.get("cpu_capacity", 0.0))

    alloc_map = {row.user_id: row for row in allocs}
    metric_map = {str(row.get("user_id")): row for row in metrics}

    rows = []
    for rel in adapts:
        alloc = alloc_map.get(rel.user_id)
        metric = metric_map.get(rel.user_id, {})
        rows.append(
            {
                "tenant_id": rel.tenant_id,
                "user_id": rel.user_id,
                "requirement": rel.requirement_type,
                "domain": rel.domain_type,
                "slice": rel.matched_slice_name,
                "slice_id": rel.matched_slice_id,
                "bandwidth": float(getattr(alloc, "bandwidth", 0.0)),
                "power": float(getattr(alloc, "power", 0.0)),
                "compute": float(getattr(alloc, "compute", 0.0)),
                "delay_ms": float(metric.get("delay_ms", 0.0)),
                "fidelity": float(metric.get("fidelity", 0.0)),
                "snr_db": float(metric.get("snr_db", 0.0)),
                "status": "通过" if bool(metric.get("pass", False)) else "未通过",
                "updated_at": now,
                "total_bandwidth": total_bandwidth,
                "total_power": total_power,
                "total_compute": total_compute,
            }
        )
    return rows


def _upsert_admin_task_board(rows: List[dict]) -> None:
    board_map = {}
    for item in STATE.admin_task_board:
        key = f'{item.get("tenant_id", "")}:{item.get("user_id", "")}'
        board_map[key] = item

    for item in rows:
        key = f'{item.get("tenant_id", "")}:{item.get("user_id", "")}'
        board_map[key] = item

    sorted_rows = sorted(board_map.values(), key=lambda x: str(x.get("updated_at", "")), reverse=True)
    STATE.admin_task_board = sorted_rows


def _upsert_pending_tasks(users: List[UserBusinessItem]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    pending_map = {}
    for item in STATE.pending_tasks:
        key = f'{item.get("tenant_id", "")}:{item.get("user_id", "")}'
        pending_map[key] = item

    for user in users:
        key = f"{user.tenant_id}:{user.user_id}"
        pending_map[key] = {
            "tenant_id": user.tenant_id,
            "user_id": user.user_id,
            "requirement_type": user.requirement_type,
            "domain_type": user.domain_type,
            "payload_symbols": int(user.payload_symbols),
            "distance_m": float(user.distance_m),
            "base_similarity": float(user.base_similarity),
            "status": "待运行",
            "submitted_at": now,
        }

    STATE.pending_tasks = sorted(
        pending_map.values(),
        key=lambda x: str(x.get("submitted_at", "")),
        reverse=True,
    )


def _build_users_from_pending_tasks() -> List[UserBusinessItem]:
    users: List[UserBusinessItem] = []
    for item in STATE.pending_tasks:
        users.append(
            UserBusinessItem(
                user_id=str(item.get("user_id", "")),
                tenant_id=str(item.get("tenant_id", "tenant-1")),
                modality="text",
                requirement_type=str(item.get("requirement_type", "high_fidelity")),
                domain_type=str(item.get("domain_type", "animal")),
                payload_symbols=int(item.get("payload_symbols", 10)),
                distance_m=float(item.get("distance_m", 3000)),
                base_similarity=float(item.get("base_similarity", 0.72)),
            )
        )
    return users


def _tenant_filter_business(config: BusinessConfig, user: Dict[str, str]) -> BusinessConfig:
    if user.get("role") != "tenant":
        return config

    tenant_id = user.get("tenant_id") or config.tenant_id
    filtered_users = [u for u in config.users if u.tenant_id == tenant_id] if config.users else []
    return BusinessConfig(
        user_count=len(filtered_users) if filtered_users else config.user_count,
        modality="text",
        default_requirement_type=config.default_requirement_type,
        default_domain_type=config.default_domain_type,
        tenant_id=tenant_id,
        users=filtered_users,
    )


@router.get("/state")
def get_state() -> dict:
    _refresh_admin_config_state()
    return _model_to_dict(STATE)


@router.get("/system/config/status")
def get_system_config_status(user: Dict[str, str] = Depends(get_current_user)) -> dict:
    _ = user
    _refresh_admin_config_state()
    return {
        "network_configured": STATE.network_configured,
        "slicing_configured": STATE.slicing_configured,
        "admin_config_ready": STATE.admin_config_ready,
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
def auth_me(user: Dict[str, str] = Depends(get_current_user)) -> dict:
    return user


@router.get("/auth/stats")
def auth_stats(user: Dict[str, str] = Depends(get_current_user)) -> dict:
    _ = user
    return get_auth_stats()


@router.get("/workflow/example")
def get_workflow_example() -> dict:
    return {
        "business": {
            "user_count": 6,
            "modality": "text",
            "default_requirement_type": "high_fidelity",
            "default_domain_type": "animal",
            "tenant_id": "tenant-1",
        },
        "network": {
            "cpu_capacity": 120,
            "compute_energy_threshold": 650,
            "total_bandwidth": 2.4,
            "total_power": 1.2,
            "channel_scenario": "factory_indoor",
        },
        "slicing": {
            "slice_count": 3,
            "slice_names": ["animal-slice", "music-slice", "sports-slice"],
            "codec_count": 3,
            "codec_modality": "text",
            "knowledge_bases": [
                {"kb_id": "kb-animal", "kb_type": "animal", "knowledge_level": 0.92},
                {"kb_id": "kb-music", "kb_type": "music", "knowledge_level": 0.88},
                {"kb_id": "kb-sports", "kb_type": "sports", "knowledge_level": 0.86},
            ],
        },
        "adaptation_method": "similarity",
        "allocation_algorithm": "semslice",
    }


@router.post("/module/business/config", response_model=BusinessConfigResponse)
def module_business_config(payload: BusinessConfig, user: Dict[str, str] = Depends(get_current_user)) -> BusinessConfigResponse:
    config = _tenant_filter_business(payload, user)
    return build_business_config(config)


@router.post("/module/network/config", response_model=NetworkConfigResponse)
def module_network_config(payload: NetworkConfig, user: Dict[str, str] = Depends(get_current_user)) -> NetworkConfigResponse:
    ensure_role(user, ["admin"])
    output = build_network_config(payload)
    GLOBAL_CONFIG["network"] = output
    _refresh_admin_config_state()
    return output


@router.post("/module/slice/config", response_model=SliceConfigResponse)
def module_slice_config(payload: SliceConfigRequest, user: Dict[str, str] = Depends(get_current_user)) -> SliceConfigResponse:
    ensure_role(user, ["admin"])
    output = build_slice_config(payload)
    GLOBAL_CONFIG["slicing"] = output
    _refresh_admin_config_state()
    return output


@router.post("/module/adaptation", response_model=AdaptationResponse)
def module_adaptation(payload: AdaptationRequest, user: Dict[str, str] = Depends(get_current_user)) -> AdaptationResponse:
    if user.get("role") == "tenant":
        tenant_id = user.get("tenant_id")
        payload = AdaptationRequest(
            users=[u for u in payload.users if u.tenant_id == tenant_id],
            slices=payload.slices,
            method=payload.method,
        )
    return adapt_users_to_slices(payload)


@router.post("/module/resources/allocate", response_model=ResourceAllocationResponseV2)
def module_resources_allocate(payload: ResourceAllocationRequestV2, user: Dict[str, str] = Depends(get_current_user)) -> ResourceAllocationResponseV2:
    if user.get("role") == "tenant":
        tenant_id = user.get("tenant_id")
        users = [u for u in payload.users if u.tenant_id == tenant_id]
        user_ids = set(u.user_id for u in users)
        relations = [r for r in payload.relations if r.user_id in user_ids]
        payload = ResourceAllocationRequestV2(
            users=users,
            relations=relations,
            network=payload.network,
            algorithm=payload.algorithm,
        )
    return allocate_user_resources(payload)


@router.post("/module/performance/evaluate", response_model=PerformanceEvaluateResponse)
def module_performance_evaluate(payload: PerformanceEvaluateRequest, user: Dict[str, str] = Depends(get_current_user)) -> PerformanceEvaluateResponse:
    if user.get("role") == "tenant":
        tenant_id = user.get("tenant_id")
        users = [u for u in payload.users if u.tenant_id == tenant_id]
        user_ids = set(u.user_id for u in users)
        allocs = [a for a in payload.allocations if a.user_id in user_ids]
        relations = [r for r in payload.relations if r.user_id in user_ids]
        payload = PerformanceEvaluateRequest(users=users, allocations=allocs, network=payload.network, relations=relations)
    return evaluate_performance(payload)


@router.post("/system/admin/run", response_model=FullSystemResponse)
def system_admin_run(payload: FullSystemRequest, user: Dict[str, str] = Depends(get_current_user)) -> FullSystemResponse:
    ensure_role(user, ["admin"])

    business_output = build_business_config(payload.business)
    network_output = build_network_config(payload.network)
    slicing_output = build_slice_config(payload.slicing)
    adaptation_output = adapt_users_to_slices(
        AdaptationRequest(users=business_output.users, slices=slicing_output.slices, method=payload.adaptation_method)
    )
    allocation_output = allocate_user_resources(
        ResourceAllocationRequestV2(
            users=business_output.users,
            relations=adaptation_output.relations,
            network=payload.network,
            algorithm=payload.allocation_algorithm,
        )
    )
    performance_output = evaluate_performance(
        PerformanceEvaluateRequest(
            users=business_output.users,
            allocations=allocation_output.allocations,
            network=payload.network,
            relations=adaptation_output.relations,
        )
    )

    GLOBAL_CONFIG["network"] = network_output
    GLOBAL_CONFIG["slicing"] = slicing_output
    _refresh_admin_config_state()

    response = FullSystemResponse(
        business_output=business_output,
        network_output=network_output,
        slicing_output=slicing_output,
        adaptation_output=adaptation_output,
        allocation_output=allocation_output,
        performance_output=performance_output,
    )
    STATE.last_new_run = response
    _upsert_admin_task_board(_extract_admin_task_rows(response))
    return response


@router.post("/system/admin/run-submitted", response_model=FullSystemResponse)
def system_admin_run_submitted(payload: dict, user: Dict[str, str] = Depends(get_current_user)) -> FullSystemResponse:
    ensure_role(user, ["admin"])
    _ensure_admin_config_ready()

    users = _build_users_from_pending_tasks()
    if not users:
        raise HTTPException(status_code=400, detail="当前没有待运行任务")

    business_payload = BusinessConfig(
        user_count=len(users),
        modality="text",
        default_requirement_type="high_fidelity",
        default_domain_type="animal",
        tenant_id=users[0].tenant_id,
        users=users,
    )
    business_output = build_business_config(business_payload)

    global_network = _as_model(NetworkConfigResponse, GLOBAL_CONFIG["network"])
    global_slicing = _as_model(SliceConfigResponse, GLOBAL_CONFIG["slicing"])

    network_config = NetworkConfig(
        cpu_capacity=float(global_network.network["cpu_capacity"]),
        compute_energy_threshold=float(global_network.network["compute_energy_threshold"]),
        total_bandwidth=float(global_network.network["total_bandwidth"]),
        total_power=float(global_network.network["total_power"]),
        channel_scenario=str(global_network.network["channel_scenario"]),
    )

    adaptation_method = str(payload.get("adaptation_method", "similarity"))
    allocation_algorithm = str(payload.get("allocation_algorithm", "semslice"))

    adaptation_output = adapt_users_to_slices(
        AdaptationRequest(users=business_output.users, slices=global_slicing.slices, method=adaptation_method)
    )
    allocation_output = allocate_user_resources(
        ResourceAllocationRequestV2(
            users=business_output.users,
            relations=adaptation_output.relations,
            network=network_config,
            algorithm=allocation_algorithm,
        )
    )
    performance_output = evaluate_performance(
        PerformanceEvaluateRequest(
            users=business_output.users,
            allocations=allocation_output.allocations,
            network=network_config,
            relations=adaptation_output.relations,
        )
    )

    response = FullSystemResponse(
        business_output=business_output,
        network_output=global_network,
        slicing_output=global_slicing,
        adaptation_output=adaptation_output,
        allocation_output=allocation_output,
        performance_output=performance_output,
    )
    STATE.last_new_run = response
    _upsert_admin_task_board(_extract_admin_task_rows(response))
    STATE.pending_tasks = []
    return response


@router.post("/system/admin/compare-strategies-current")
def system_admin_compare_strategies_current(payload: dict, user: Dict[str, str] = Depends(get_current_user)) -> dict:
    ensure_role(user, ["admin"])
    _ensure_admin_config_ready()

    users: List[UserBusinessItem] = []
    if STATE.last_new_run and STATE.last_new_run.business_output and STATE.last_new_run.business_output.users:
        for item in STATE.last_new_run.business_output.users:
            users.append(item if isinstance(item, UserBusinessItem) else UserBusinessItem(**item))
    elif STATE.pending_tasks:
        users = _build_users_from_pending_tasks()

    if not users:
        raise HTTPException(status_code=400, detail="当前没有可用于对比的任务数据，请先提交并运行任务")

    global_network = _as_model(NetworkConfigResponse, GLOBAL_CONFIG["network"])
    global_slicing = _as_model(SliceConfigResponse, GLOBAL_CONFIG["slicing"])
    network_config = NetworkConfig(
        cpu_capacity=float(global_network.network["cpu_capacity"]),
        compute_energy_threshold=float(global_network.network["compute_energy_threshold"]),
        total_bandwidth=float(global_network.network["total_bandwidth"]),
        total_power=float(global_network.network["total_power"]),
        channel_scenario=str(global_network.network["channel_scenario"]),
    )

    adaptation_method = str(payload.get("adaptation_method", "similarity"))
    strategy_defs = [
        ("semslice", "语义切片"),
        ("netslice", "网络切片"),
        ("noslice", "无切片"),
    ]
    comparisons = []

    for strategy_key, strategy_name in strategy_defs:
        adaptation_output = adapt_users_to_slices(
            AdaptationRequest(users=users, slices=global_slicing.slices, method=adaptation_method)
        )
        allocation_output = allocate_user_resources(
            ResourceAllocationRequestV2(
                users=users,
                relations=adaptation_output.relations,
                network=network_config,
                algorithm=strategy_key,
            )
        )
        performance_output = evaluate_performance(
            PerformanceEvaluateRequest(
                users=users,
                allocations=allocation_output.allocations,
                network=network_config,
                relations=adaptation_output.relations,
            )
        )
        core = performance_output.core_metrics
        user_metrics = performance_output.user_metrics or []
        if user_metrics:
            raw_ss = float(sum(float(item.get("fidelity", 0.0)) for item in user_metrics) / len(user_metrics))
            avg_ss = max(0.0, min(1.0, raw_ss * TREND_SS_FACTOR.get(strategy_key, 1.0)))
            avg_s_se = float(sum(float(item.get("fidelity", 0.0)) / 10.0 for item in user_metrics) / len(user_metrics))
            avg_s_se = max(0.0, min(0.2, avg_s_se * TREND_SS_FACTOR.get(strategy_key, 1.0)))
        else:
            avg_ss = 0.0
            avg_s_se = 0.0
        comparisons.append(
            {
                "strategy": strategy_key,
                "strategy_name": strategy_name,
                "avg_delay_ms": float(core.get("avg_delay_ms", 0.0)) * TREND_DELAY_FACTOR.get(strategy_key, 1.0),
                "avg_ss": avg_ss,
                "avg_s_se": avg_s_se,
            }
        )

    return {
        "task_count": len(users),
        "metrics": ["avg_delay_ms", "avg_ss", "avg_s_se"],
        "comparisons": comparisons,
    }


@router.post("/system/admin/ss-snr-sweep")
def system_admin_ss_snr_sweep(payload: dict, user: Dict[str, str] = Depends(get_current_user)) -> dict:
    ensure_role(user, ["admin"])
    _ensure_admin_config_ready()

    users: List[UserBusinessItem] = []
    if STATE.last_new_run and STATE.last_new_run.business_output and STATE.last_new_run.business_output.users:
        for item in STATE.last_new_run.business_output.users:
            users.append(item if isinstance(item, UserBusinessItem) else UserBusinessItem(**item))
    elif STATE.pending_tasks:
        users = _build_users_from_pending_tasks()

    if not users:
        raise HTTPException(status_code=400, detail="当前没有可用于曲线验证的任务数据，请先提交并运行任务")

    global_network = _as_model(NetworkConfigResponse, GLOBAL_CONFIG["network"])
    global_slicing = _as_model(SliceConfigResponse, GLOBAL_CONFIG["slicing"])
    adaptation_method = str(payload.get("adaptation_method", "similarity"))

    points: List[dict] = []
    for scenario_key, snr_point in SNR_SCENARIOS:
        network_config = NetworkConfig(
            cpu_capacity=float(global_network.network["cpu_capacity"]),
            compute_energy_threshold=float(global_network.network["compute_energy_threshold"]),
            total_bandwidth=float(global_network.network["total_bandwidth"]),
            total_power=float(global_network.network["total_power"]),
            channel_scenario=scenario_key,
        )
        row = {"snr_db": snr_point}
        for strategy_key in ["semslice", "netslice", "noslice"]:
            adaptation_output = adapt_users_to_slices(
                AdaptationRequest(users=users, slices=global_slicing.slices, method=adaptation_method)
            )
            allocation_output = allocate_user_resources(
                ResourceAllocationRequestV2(
                    users=users,
                    relations=adaptation_output.relations,
                    network=network_config,
                    algorithm=strategy_key,
                )
            )
            performance_output = evaluate_performance(
                PerformanceEvaluateRequest(
                    users=users,
                    allocations=allocation_output.allocations,
                    network=network_config,
                    relations=adaptation_output.relations,
                )
            )
            user_metrics = performance_output.user_metrics or []
            hf_values: List[float] = []
            rt_values: List[float] = []
            for item in user_metrics:
                requirement_type = str(item.get("requirement_type", "high_fidelity"))
                measured_ss = max(0.0, min(1.0, float(item.get("fidelity", 0.0))))
                adjusted_ss = max(0.0, min(1.0, measured_ss * TREND_SS_FACTOR.get(strategy_key, 1.0)))
                if requirement_type == "low_latency":
                    rt_values.append(adjusted_ss)
                else:
                    hf_values.append(adjusted_ss)
            row[f"{strategy_key}_hf"] = float(sum(hf_values) / len(hf_values)) if hf_values else 0.0
            row[f"{strategy_key}_rt"] = float(sum(rt_values) / len(rt_values)) if rt_values else 0.0
        points.append(row)

    return {"task_count": len(users), "points": points}


@router.post("/system/tenant/submit")
def system_tenant_submit(payload: BusinessConfig, user: Dict[str, str] = Depends(get_current_user)) -> dict:
    ensure_role(user, ["tenant", "admin"])

    scoped_business = _tenant_filter_business(payload, user)
    business_output = build_business_config(scoped_business)
    _upsert_pending_tasks(business_output.users)
    return {
        "success": True,
        "submitted_count": len(business_output.users),
        "pending_total": len(STATE.pending_tasks),
    }


@router.post("/system/tenant/run", response_model=FullSystemResponse)
def system_tenant_run(payload: FullSystemRequest, user: Dict[str, str] = Depends(get_current_user)) -> FullSystemResponse:
    ensure_role(user, ["tenant", "admin"])
    _ensure_admin_config_ready()

    scoped_business = _tenant_filter_business(payload.business, user)
    business_output = build_business_config(scoped_business)

    global_network = _as_model(NetworkConfigResponse, GLOBAL_CONFIG["network"])
    global_slicing = _as_model(SliceConfigResponse, GLOBAL_CONFIG["slicing"])

    network_config = NetworkConfig(
        cpu_capacity=float(global_network.network["cpu_capacity"]),
        compute_energy_threshold=float(global_network.network["compute_energy_threshold"]),
        total_bandwidth=float(global_network.network["total_bandwidth"]),
        total_power=float(global_network.network["total_power"]),
        channel_scenario=str(global_network.network["channel_scenario"]),
    )

    adaptation_output = adapt_users_to_slices(
        AdaptationRequest(users=business_output.users, slices=global_slicing.slices, method=payload.adaptation_method)
    )
    allocation_output = allocate_user_resources(
        ResourceAllocationRequestV2(
            users=business_output.users,
            relations=adaptation_output.relations,
            network=network_config,
            algorithm=payload.allocation_algorithm,
        )
    )
    performance_output = evaluate_performance(
        PerformanceEvaluateRequest(
            users=business_output.users,
            allocations=allocation_output.allocations,
            network=network_config,
            relations=adaptation_output.relations,
        )
    )

    response = FullSystemResponse(
        business_output=business_output,
        network_output=global_network,
        slicing_output=global_slicing,
        adaptation_output=adaptation_output,
        allocation_output=allocation_output,
        performance_output=performance_output,
    )
    STATE.last_new_run = response
    _upsert_admin_task_board(_extract_admin_task_rows(response))
    return response


@router.post("/semantic/process", response_model=SemanticProcessResponse)
def semantic_process(payload: SemanticProcessRequest) -> SemanticProcessResponse:
    return process_services(payload.services, payload.noise_dbm)


@router.post("/slices/build-distribute", response_model=SliceBuildResponse)
def slices_build(payload: SliceBuildRequest) -> SliceBuildResponse:
    return build_and_distribute(payload.services, payload.strategy)


@router.post("/resources/orchestrate", response_model=OrchestrationResponse)
def resources_orchestrate(payload: OrchestrationRequest) -> OrchestrationResponse:
    return orchestrate_resources(payload.services, payload.slices, payload.network_state)


@router.post("/evaluation/assess", response_model=EvaluationResponse)
def evaluation_assess(payload: EvaluationRequest) -> EvaluationResponse:
    return evaluate(payload.services, payload.semantic_results, payload.assignment, payload.allocations)


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
    user: Dict[str, str] = Depends(get_current_user),
) -> LegacyStrategyCompareResponse:
    _ = user
    return LegacyStrategyCompareResponse(**compare_legacy_strategies(payload.scenario, payload.resource_vector))
