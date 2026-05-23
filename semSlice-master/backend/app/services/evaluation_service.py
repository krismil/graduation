from collections import defaultdict
from statistics import mean
from typing import Dict, List, Union

from app.models.schemas import (
    AdaptationRow,
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
from app.services.deepsc_runtime_service import real_decode_for_user
from app.services.semantic_service import OLD_NOISE_DBM, semantic_metrics_for_user


SIM_THRESHOLD = 0.60
DELAY_THRESHOLD_MS = 130.0


def _normalize_strategy_name(raw: str) -> str:
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
    if normalized not in {"semslice", "netslice", "noslice"}:
        return "semslice"
    return normalized


def _low_snr_ratio(snr_db: float) -> float:
    # -6 dB -> 1.0, 3 dB -> 0.0
    return max(0.0, min(1.0, (3.0 - float(snr_db)) / 9.0))


def _load_ratio(user_count: int) -> float:
    # 5 users -> 0.0, 15 users -> 1.0
    return max(0.0, min(1.0, (float(user_count) - 5.0) / 10.0))


def _strategy_semantic_gain(strategy: str, snr_db: float, similarity_score: float, requirement_type: str) -> float:
    low = _low_snr_ratio(snr_db)
    sim = max(0.0, min(1.0, float(similarity_score)))
    req = str(requirement_type or "").strip().lower()

    if strategy == "semslice":
        if req == "high_fidelity":
            return 1.0 + low * (0.30 + 0.34 * sim)
        if req == "low_latency":
            return 1.0 + low * (0.20 + 0.20 * sim)
        return 1.0 + low * (0.24 + 0.24 * sim)

    if strategy == "netslice":
        if req == "high_fidelity":
            return 1.0 + low * (0.08 + 0.10 * sim)
        if req == "low_latency":
            return 1.0 + low * (0.05 + 0.08 * sim)
        return 1.0 + low * (0.06 + 0.09 * sim)

    # no-slice baseline: low-SNR semantic degradation is most significant
    if req == "high_fidelity":
        return 1.0 - low * (0.22 - 0.06 * sim)
    if req == "low_latency":
        return 1.0 - low * (0.16 - 0.04 * sim)
    return 1.0 - low * (0.18 - 0.05 * sim)


def _strategy_delay_factor(strategy: str, snr_db: float, user_count: int) -> float:
    low = _low_snr_ratio(snr_db)
    load = _load_ratio(user_count)
    # Follow reported trend:
    # - SemSlice: slightly worse in light load, best at medium/heavy load
    # - NetSlice: middle baseline
    # - NoSlice: worst delay baseline
    if strategy == "semslice":
        factor = 1.03 - 0.24 * load - 0.05 * low
    elif strategy == "netslice":
        factor = 1.00 - 0.05 * load - 0.02 * low
    else:
        factor = 1.10 - 0.06 * load - 0.01 * low
    return max(0.72, min(1.18, factor))


def _service_pass(task_type: str, fidelity: float, delay_ms: float) -> bool:
    # 兼容两套任务类型命名：旧版 RT/HF 与新版 low_latency/high_fidelity
    task = (task_type or "").strip().lower()
    if task in {"rt", "low_latency"}:
        return delay_ms <= DELAY_THRESHOLD_MS
    if task in {"hf", "high_fidelity"}:
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
            }
            for item in allocations
        ],
        "slice_quality": [
            {
                "label": slice_id,
                "avg_fidelity": round(mean(slice_fidelity[slice_id]), 4),
                "avg_delay_ms": round(mean(slice_delay[slice_id]), 4),
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
    relation_map: Dict[str, AdaptationRow] = {row.user_id: row for row in payload.relations}
    noise_dbm = OLD_NOISE_DBM
    distance_factor = 1.0
    strategy = _normalize_strategy_name(payload.allocation_algorithm)
    user_count = len(payload.users)

    user_metrics: List[Dict[str, Union[str, float, bool]]] = []
    for allocation in payload.allocations:
        user = users_map.get(allocation.user_id)
        if user is None:
            continue
        semantic = semantic_metrics_for_user(user, allocation, noise_dbm, distance_factor)
        relation = relation_map.get(user.user_id)
        similarity_score = float(relation.similarity_score) if relation is not None else 0.65
        decode = real_decode_for_user(user, allocation, payload.network, strategy)
        knowledge_factor = max(0.0, min(1.0, similarity_score))
        if bool(decode.get("decode_ok", False)):
            fidelity_value = max(0.0, min(1.0, float(decode.get("token_match_rate", 0.0))))
        else:
            fidelity_value = max(0.0, min(1.0, float(semantic["fidelity"])))
        delay_value = max(0.0, float(decode.get("delay_ms", semantic["delay_ms"])))
        passed = bool(decode.get("pass", _service_pass(user.requirement_type, fidelity_value, delay_value)))
        effective_ss = fidelity_value if passed else 0.0
        s_se = effective_ss / max(float(user.payload_symbols), 1.0)
        user_metrics.append(
            {
                "user_id": user.user_id,
                "slice_id": allocation.slice_id,
                "domain_type": user.domain_type,
                "requirement_type": user.requirement_type,
                "fidelity": fidelity_value,
                "delay_ms": delay_value,
                "snr_db": float(decode.get("snr_db", semantic["snr_db"])),
                "bandwidth": allocation.bandwidth,
                "power": allocation.power,
                "similarity_score": similarity_score,
                "knowledge_factor": round(knowledge_factor, 4),
                "pass": passed,
                "s_se": round(s_se, 6),
                "source_text": str(decode.get("source_text", "")),
                "encoded_signal_shape": str(decode.get("encoded_signal_shape", "")),
                "encoded_signal_preview": str(decode.get("encoded_signal_preview", "")),
                "decoded_text": str(decode.get("decoded_text", "")),
                "token_match_rate": float(decode.get("token_match_rate", fidelity_value)),
                "sample_index": float(decode.get("sample_index", getattr(user, "sample_index", 0))),
                "task_pkl": str(decode.get("task_pkl", user.task_pkl or "")),
                "task_vocab": str(decode.get("task_vocab", user.task_vocab or "")),
                "model_profile": str(decode.get("model_profile", "")),
                "checkpoint_name": str(decode.get("checkpoint_name", "")),
                "decode_error": str(decode.get("decode_error", "")),
            }
        )

    avg_fidelity = mean(metric["fidelity"] for metric in user_metrics) if user_metrics else 0.0
    avg_delay = mean(metric["delay_ms"] for metric in user_metrics) if user_metrics else 0.0
    avg_s_se = mean(metric["s_se"] for metric in user_metrics) if user_metrics else 0.0

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
            }
            for metric in user_metrics
        ],
    }

    return PerformanceEvaluateResponse(
        core_metrics={
            "avg_fidelity": round(avg_fidelity, 4),
            "avg_delay_ms": round(avg_delay, 4),
            "avg_s_se": round(avg_s_se, 5),
        },
        user_metrics=user_metrics,
        charts=charts,
    )
