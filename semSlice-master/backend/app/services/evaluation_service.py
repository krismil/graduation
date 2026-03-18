from collections import defaultdict
from statistics import mean
from typing import Dict, List, Union

from app.models.schemas import (
    EvaluationResponse,
    NetworkConfig,
    PerformanceEvaluateRequest,
    PerformanceEvaluateResponse,
    ResourceAllocationItem,
    SemanticResultItem,
    ServiceProfile,
    UserBusinessItem,
    UserResourceAllocation,
)
from app.services.semantic_service import CHANNEL_SCENARIOS, semantic_metrics_for_user


SIM_THRESHOLD = 0.60
DELAY_THRESHOLD_MS = 130.0


def _service_pass(task_type: str, fidelity: float, delay_ms: float) -> bool:
    if task_type == "RT":
        return delay_ms <= DELAY_THRESHOLD_MS
    if task_type == "HF":
        return fidelity >= SIM_THRESHOLD
    return fidelity >= 0.55 and delay_ms <= 180


def evaluate(
    services: List[ServiceProfile],
    semantic_results: List[SemanticResultItem],
    assignment: Dict[str, str],
    allocations: List[ResourceAllocationItem],
) -> EvaluationResponse:
    service_map = {service.service_id: service for service in services}
    allocation_map = {item.slice_id: item for item in allocations}

    service_metrics: List[Dict[str, Union[float, str, bool]]] = []

    for result in semantic_results:
        service = service_map[result.service_id]
        slice_id = assignment.get(result.service_id, "unknown")
        passed = _service_pass(service.task_type, result.semantic_fidelity, result.tx_delay_ms)

        service_metrics.append(
            {
                "service_id": service.service_id,
                "slice_id": slice_id,
                "task_type": service.task_type,
                "fidelity": result.semantic_fidelity,
                "delay_ms": result.tx_delay_ms,
                "snr_db": result.snr_db,
                "pass": passed,
            }
        )

    avg_fidelity = mean(row["fidelity"] for row in service_metrics) if service_metrics else 0.0
    avg_delay_ms = mean(row["delay_ms"] for row in service_metrics) if service_metrics else 0.0
    pass_rate = mean(1.0 if row["pass"] else 0.0 for row in service_metrics) if service_metrics else 0.0

    slice_fidelity: Dict[str, List[float]] = defaultdict(list)
    slice_delay: Dict[str, List[float]] = defaultdict(list)
    for row in service_metrics:
        sid = str(row["slice_id"])
        slice_fidelity[sid].append(float(row["fidelity"]))
        slice_delay[sid].append(float(row["delay_ms"]))

    chart_data = {
        "fidelity_by_service": [
            {"label": row["service_id"], "value": float(row["fidelity"])} for row in service_metrics
        ],
        "delay_by_service": [
            {"label": row["service_id"], "value": float(row["delay_ms"])} for row in service_metrics
        ],
        "slice_resource": [
            {
                "label": item.slice_id,
                "power": item.power,
                "bandwidth": item.bandwidth,
                "compute": item.compute,
            }
            for item in allocations
        ],
        "slice_quality": [
            {
                "label": slice_id,
                "avg_fidelity": round(mean(slice_fidelity[slice_id]), 4),
                "avg_delay_ms": round(mean(slice_delay[slice_id]), 4),
                "compute": allocation_map.get(slice_id).compute if slice_id in allocation_map else 0.0,
            }
            for slice_id in sorted(slice_fidelity.keys())
        ],
    }

    core_metrics = {
        "avg_fidelity": round(avg_fidelity, 4),
        "avg_e2e_delay_ms": round(avg_delay_ms, 4),
        "service_pass_rate": round(pass_rate, 4),
    }

    return EvaluationResponse(
        core_metrics=core_metrics,
        service_metrics=service_metrics,
        chart_data=chart_data,
    )


def evaluate_performance(payload: PerformanceEvaluateRequest) -> PerformanceEvaluateResponse:
    users_map: Dict[str, UserBusinessItem] = {user.user_id: user for user in payload.users}
    scenario_profile = CHANNEL_SCENARIOS.get(payload.network.channel_scenario, CHANNEL_SCENARIOS["factory_indoor"])
    noise_dbm = float(scenario_profile["noise_dbm"])
    distance_factor = float(scenario_profile["distance_factor"])

    user_metrics: List[Dict[str, Union[str, float, bool]]] = []
    for allocation in payload.allocations:
        user = users_map.get(allocation.user_id)
        if user is None:
            continue
        semantic = semantic_metrics_for_user(user, allocation, noise_dbm, distance_factor)
        passed = _service_pass(user.requirement_type, semantic["fidelity"], semantic["delay_ms"])
        user_metrics.append(
            {
                "user_id": user.user_id,
                "tenant_id": user.tenant_id,
                "slice_id": allocation.slice_id,
                "domain_type": user.domain_type,
                "requirement_type": user.requirement_type,
                "fidelity": semantic["fidelity"],
                "delay_ms": semantic["delay_ms"],
                "snr_db": semantic["snr_db"],
                "bandwidth": allocation.bandwidth,
                "power": allocation.power,
                "compute": allocation.compute,
                "energy_cost": allocation.energy_cost,
                "pass": passed,
            }
        )

    avg_fidelity = mean(metric["fidelity"] for metric in user_metrics) if user_metrics else 0.0
    avg_delay = mean(metric["delay_ms"] for metric in user_metrics) if user_metrics else 0.0
    pass_rate = mean(1.0 if metric["pass"] else 0.0 for metric in user_metrics) if user_metrics else 0.0
    avg_energy = mean(metric["energy_cost"] for metric in user_metrics) if user_metrics else 0.0

    charts = {
        "fidelity_by_user": [
            {"label": metric["user_id"], "value": float(metric["fidelity"])} for metric in user_metrics
        ],
        "delay_by_user": [
            {"label": metric["user_id"], "value": float(metric["delay_ms"])} for metric in user_metrics
        ],
        "resource_by_user": [
            {
                "label": metric["user_id"],
                "bandwidth": float(metric["bandwidth"]),
                "power": float(metric["power"]),
                "compute": float(metric["compute"]),
                "energy": float(metric["energy_cost"]),
            }
            for metric in user_metrics
        ],
    }

    return PerformanceEvaluateResponse(
        core_metrics={
            "avg_fidelity": round(avg_fidelity, 4),
            "avg_delay_ms": round(avg_delay, 4),
            "pass_rate": round(pass_rate, 4),
            "avg_energy": round(avg_energy, 4),
        },
        user_metrics=user_metrics,
        charts=charts,
    )
