from typing import Dict, List

from fastapi import APIRouter, Depends, Header

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
    LegacyRunRequest,
    LegacyRunResponse,
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
    WorkflowRequest,
    WorkflowResponse,
)
from app.services.adaptation_service import adapt_users_to_slices
from app.services.auth_service import (
    ensure_role,
    extract_token_from_header,
    get_current_user,
    login,
    logout,
)
from app.services.evaluation_service import evaluate, evaluate_performance
from app.services.legacy_adapter import compare_legacy_strategies, run_legacy
from app.services.orchestration_service import allocate_user_resources, orchestrate_resources
from app.services.semantic_service import build_business_config, build_network_config, process_services
from app.services.slicing_service import build_and_distribute, build_slice_config
from app.store.state import STATE


router = APIRouter()

GLOBAL_CONFIG = {
    "network": build_network_config(NetworkConfig()),
    "slicing": build_slice_config(SliceConfigRequest()),
}


def _model_to_dict(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _as_model(model_class, value):
    if isinstance(value, model_class):
        return value
    return model_class(**value)


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
    return _model_to_dict(STATE)


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
        "allocation_algorithm": "pso",
        "allocation_backend": "online_pso",
        "legacy_strategy": "semslice",
        "legacy_scenario": "fitSNR",
        "legacy_iterations": 2,
        "legacy_particles": 2,
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
    return output


@router.post("/module/slice/config", response_model=SliceConfigResponse)
def module_slice_config(payload: SliceConfigRequest, user: Dict[str, str] = Depends(get_current_user)) -> SliceConfigResponse:
    ensure_role(user, ["admin"])
    output = build_slice_config(payload)
    GLOBAL_CONFIG["slicing"] = output
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
            allocation_backend=payload.allocation_backend,
            legacy_strategy=payload.legacy_strategy,
            legacy_scenario=payload.legacy_scenario,
            legacy_iterations=payload.legacy_iterations,
            legacy_particles=payload.legacy_particles,
        )
    return allocate_user_resources(payload)


@router.post("/module/performance/evaluate", response_model=PerformanceEvaluateResponse)
def module_performance_evaluate(payload: PerformanceEvaluateRequest, user: Dict[str, str] = Depends(get_current_user)) -> PerformanceEvaluateResponse:
    if user.get("role") == "tenant":
        tenant_id = user.get("tenant_id")
        users = [u for u in payload.users if u.tenant_id == tenant_id]
        user_ids = set(u.user_id for u in users)
        allocs = [a for a in payload.allocations if a.user_id in user_ids]
        payload = PerformanceEvaluateRequest(users=users, allocations=allocs, network=payload.network)
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
            allocation_backend=payload.allocation_backend,
            legacy_strategy=payload.legacy_strategy,
            legacy_scenario=payload.legacy_scenario,
            legacy_iterations=payload.legacy_iterations,
            legacy_particles=payload.legacy_particles,
        )
    )
    performance_output = evaluate_performance(
        PerformanceEvaluateRequest(
            users=business_output.users,
            allocations=allocation_output.allocations,
            network=payload.network,
        )
    )

    GLOBAL_CONFIG["network"] = network_output
    GLOBAL_CONFIG["slicing"] = slicing_output

    response = FullSystemResponse(
        business_output=business_output,
        network_output=network_output,
        slicing_output=slicing_output,
        adaptation_output=adaptation_output,
        allocation_output=allocation_output,
        performance_output=performance_output,
    )
    STATE.last_new_run = response
    return response


@router.post("/system/tenant/run", response_model=FullSystemResponse)
def system_tenant_run(payload: FullSystemRequest, user: Dict[str, str] = Depends(get_current_user)) -> FullSystemResponse:
    ensure_role(user, ["tenant", "admin"])

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
            allocation_backend=payload.allocation_backend,
            legacy_strategy=payload.legacy_strategy,
            legacy_scenario=payload.legacy_scenario,
            legacy_iterations=payload.legacy_iterations,
            legacy_particles=payload.legacy_particles,
        )
    )
    performance_output = evaluate_performance(
        PerformanceEvaluateRequest(
            users=business_output.users,
            allocations=allocation_output.allocations,
            network=network_config,
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
    return LegacyStrategyCompareResponse(**compare_legacy_strategies(payload.scenario, payload.resource_vector, payload.compare_mode))


@router.post("/workflow/run-legacy", response_model=LegacyRunResponse)
def workflow_run_legacy(payload: LegacyRunRequest) -> LegacyRunResponse:
    try:
        result = run_legacy(payload.strategy, payload.scenario, payload.resource_vector)
        return LegacyRunResponse(success=True, result=result)
    except Exception as error:
        return LegacyRunResponse(success=False, error=str(error))

