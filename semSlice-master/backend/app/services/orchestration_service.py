import random
from collections import defaultdict
from typing import Dict, List

from app.models.schemas import (
    AdaptationRow,
    NetworkConfig,
    OrchestrationResponse,
    ResourceAllocationItem,
    ResourceAllocationRequestV2,
    ResourceAllocationResponseV2,
    ResourceState,
    ServiceProfile,
    SliceDefinition,
    UserBusinessItem,
    UserResourceAllocation,
)
from app.services.semantic_service import OLD_DISTANCE_M, OLD_NOISE_DBM, compute_snr_db, transmit_delay_ms


DEMO_SLICE_POWER_RATIOS = (0.02 / 0.17, 0.05 / 0.17, 0.10 / 0.17)
DEMO_SLICE_BANDWIDTH_RATIOS = (0.90 / 2.0, 0.70 / 2.0, 0.40 / 2.0)
SLICE_COUNT = 3
PSO_PARTICLES = 20
PSO_ITERATIONS = 50
PSO_SEED = 2026
OLD_SYMBOL_LENGTH = 30
SIM_THRESHOLD = 0.60
DELAY_THRESHOLD_MS = 130.0
PSO_SS_WEIGHT = 1.35
PSO_DELAY_PENALTY_SCALE = 0.45


def _slice_weight(task_types: List[str], avg_semantic_nssai: float, congestion_level: float) -> float:
    task_weight = 1.0
    if "RT" in task_types:
        task_weight += 0.5
    if "HF" in task_types:
        task_weight += 0.2
    semantic_weight = 0.7 + avg_semantic_nssai / 100
    congestion_weight = 1.0 + congestion_level * 0.6
    return task_weight * semantic_weight * congestion_weight


def orchestrate_resources(
    services: List[ServiceProfile],
    slices: List[SliceDefinition],
    network_state: ResourceState,
) -> OrchestrationResponse:
    if not slices:
        return OrchestrationResponse(
            allocations=[],
            remaining={
                "power": network_state.total_power,
                "bandwidth": network_state.total_bandwidth,
            },
        )

    service_map = {service.service_id: service for service in services}

    demand_bw: Dict[str, float] = defaultdict(float)
    avg_nssai: Dict[str, float] = {}
    task_types: Dict[str, List[str]] = {}

    for slice_info in slices:
        nssai_values: List[float] = []
        types: List[str] = []
        for member in slice_info.members:
            service = service_map.get(member)
            if service is None:
                continue
            demand_bw[slice_info.slice_id] += service.request_bandwidth
            nssai_values.append(service.semantic_nssai)
            types.append(service.task_type)

        avg_nssai[slice_info.slice_id] = sum(nssai_values) / max(len(nssai_values), 1)
        task_types[slice_info.slice_id] = types

    raw_scores: Dict[str, float] = {}
    for slice_info in slices:
        sid = slice_info.slice_id
        weight = _slice_weight(task_types[sid], avg_nssai[sid], network_state.congestion_level)
        raw_scores[sid] = demand_bw[sid] * weight

    total_score = sum(raw_scores.values()) or 1.0

    allocations: List[ResourceAllocationItem] = []
    for slice_info in slices:
        ratio = max(0.05, raw_scores[slice_info.slice_id] / total_score)
        allocations.append(
            ResourceAllocationItem(
                slice_id=slice_info.slice_id,
                power=round(network_state.total_power * ratio, 5),
                bandwidth=round(network_state.total_bandwidth * ratio, 5),
            )
        )

    used_power = sum(item.power for item in allocations)
    used_bandwidth = sum(item.bandwidth for item in allocations)
    if used_power > network_state.total_power and used_power > 0:
        scale_power = network_state.total_power / used_power
        for item in allocations:
            item.power = round(item.power * scale_power, 5)
    if used_bandwidth > network_state.total_bandwidth and used_bandwidth > 0:
        scale_bandwidth = network_state.total_bandwidth / used_bandwidth
        for item in allocations:
            item.bandwidth = round(item.bandwidth * scale_bandwidth, 5)

    remaining = {
        "power": round(network_state.total_power - sum(item.power for item in allocations), 6),
        "bandwidth": round(network_state.total_bandwidth - sum(item.bandwidth for item in allocations), 6),
    }

    return OrchestrationResponse(allocations=allocations, remaining=remaining)


def _slice_index_from_id(slice_id: str) -> int:
    token = str(slice_id or "").strip().lower()
    if token.endswith("2") or "90" in token:
        return 1
    if token.endswith("3") or "80" in token:
        return 2
    return 0


def _legacy_slice_resource_table(network: NetworkConfig) -> Dict[int, Dict[str, float]]:
    return {
        idx: {
            "power": round(float(network.total_power) * DEMO_SLICE_POWER_RATIOS[idx], 5),
            "bandwidth": round(float(network.total_bandwidth) * DEMO_SLICE_BANDWIDTH_RATIOS[idx], 5),
        }
        for idx in range(3)
    }


def _noise_watts() -> float:
    return (10 ** (OLD_NOISE_DBM / 10)) * 1e-3


def _noslice_equal_resource(network: NetworkConfig) -> Dict[str, float]:
    per_slice_bandwidth_cap = float(network.total_bandwidth) / SLICE_COUNT
    per_slice_power_cap = float(network.total_power) / SLICE_COUNT
    target_linear = 10 ** (float(network.target_snr_db) / 10)
    snr_link_factor = target_linear * 1e6 * (OLD_DISTANCE_M ** 2) * _noise_watts()

    if snr_link_factor <= 0:
        return {
            "bandwidth": per_slice_bandwidth_cap,
            "power": per_slice_power_cap,
        }

    power_for_full_bandwidth = snr_link_factor * per_slice_bandwidth_cap
    if power_for_full_bandwidth <= per_slice_power_cap:
        bandwidth = per_slice_bandwidth_cap
        power = power_for_full_bandwidth
    else:
        power = per_slice_power_cap
        bandwidth = min(per_slice_bandwidth_cap, power / snr_link_factor)

    return {
        "bandwidth": max(0.0, bandwidth),
        "power": max(0.0, power),
    }


def _normalize_vector(vector: List[float], network: NetworkConfig) -> List[float]:
    values = [max(0.001, float(item)) for item in vector[: 2 * SLICE_COUNT]]
    power = values[:SLICE_COUNT]
    bandwidth = values[SLICE_COUNT:]

    target_linear = 10 ** (float(network.target_snr_db) / 10)
    n0 = _noise_watts()
    for idx, bw in enumerate(bandwidth):
        required_power = target_linear * bw * 1e6 * (OLD_DISTANCE_M ** 2) * n0
        power[idx] = min(max(required_power, 0.001), float(network.total_power) / SLICE_COUNT)

    total_power = sum(power)
    if total_power > float(network.total_power) and total_power > 0:
        scale = float(network.total_power) / total_power
        power = [item * scale for item in power]

    total_bandwidth = sum(bandwidth)
    if total_bandwidth > float(network.total_bandwidth) and total_bandwidth > 0:
        scale = float(network.total_bandwidth) / total_bandwidth
        bandwidth = [item * scale for item in bandwidth]

    return power + bandwidth


def _task_pass(requirement_type: str, fidelity: float, delay_ms: float) -> bool:
    task = str(requirement_type or "").strip().lower().replace("-", "_")
    if task == "low_latency":
        return delay_ms <= DELAY_THRESHOLD_MS
    return fidelity >= SIM_THRESHOLD


def _estimate_token_score(snr_db: float, target_snr_db: float) -> float:
    snr_bonus = 0.018 * (snr_db - target_snr_db)
    score = 0.58 + snr_bonus
    return max(0.0, min(1.0, score))


def _fitness(
    vector: List[float],
    network: NetworkConfig,
    users: List[UserBusinessItem],
    relation_slice_indices: Dict[str, int],
) -> float:
    normalized = _normalize_vector(vector, network)
    power = normalized[:SLICE_COUNT]
    bandwidth = normalized[SLICE_COUNT:]
    if not users:
        return 0.0

    scores: List[float] = []
    for user in users:
        idx = relation_slice_indices.get(user.user_id, 0)
        snr_db = compute_snr_db(
            power=max(1e-6, power[idx]),
            bandwidth_mhz=max(1e-6, bandwidth[idx]),
            distance_m=OLD_DISTANCE_M,
            noise_dbm=OLD_NOISE_DBM,
        )
        delay_ms = transmit_delay_ms(int(user.payload_symbols), OLD_SYMBOL_LENGTH, max(1e-6, bandwidth[idx]), snr_db)
        token_score = _estimate_token_score(snr_db=snr_db, target_snr_db=float(network.target_snr_db))
        passed = _task_pass(user.requirement_type, token_score, delay_ms)
        effective_ss = token_score if passed else 0.0
        delay_penalty = min(0.35, delay_ms / 1000.0) * PSO_DELAY_PENALTY_SCALE
        scores.append(PSO_SS_WEIGHT * effective_ss - delay_penalty)
    return sum(scores) / len(scores)


def _pso_slice_resource_table(
    users: List[UserBusinessItem],
    relations: List[AdaptationRow],
    network: NetworkConfig,
) -> Dict[int, Dict[str, float]]:
    relation_slice_indices = {
        relation.user_id: _slice_index_from_id(relation.matched_slice_id)
        for relation in relations
    }
    rng = random.Random(PSO_SEED + int(round(float(network.target_snr_db) * 10)))
    lower = [0.001] * (2 * SLICE_COUNT)
    upper = [float(network.total_power)] * SLICE_COUNT + [float(network.total_bandwidth)] * SLICE_COUNT

    positions = [
        _normalize_vector([rng.uniform(lower[idx], upper[idx]) for idx in range(2 * SLICE_COUNT)], network)
        for _ in range(PSO_PARTICLES)
    ]
    velocities = [[rng.uniform(-0.1, 0.1) for _ in range(2 * SLICE_COUNT)] for _ in range(PSO_PARTICLES)]
    personal_best = [position[:] for position in positions]
    personal_scores = [_fitness(position, network, users, relation_slice_indices) for position in personal_best]
    best_index = max(range(PSO_PARTICLES), key=lambda idx: personal_scores[idx])
    global_best = personal_best[best_index][:]
    global_score = personal_scores[best_index]

    for _ in range(PSO_ITERATIONS):
        for particle_idx in range(PSO_PARTICLES):
            for dim in range(2 * SLICE_COUNT):
                velocities[particle_idx][dim] = (
                    0.62 * velocities[particle_idx][dim]
                    + 1.35 * rng.random() * (personal_best[particle_idx][dim] - positions[particle_idx][dim])
                    + 1.35 * rng.random() * (global_best[dim] - positions[particle_idx][dim])
                )
                velocities[particle_idx][dim] = max(-0.2, min(0.2, velocities[particle_idx][dim]))
                positions[particle_idx][dim] = max(lower[dim], min(upper[dim], positions[particle_idx][dim] + velocities[particle_idx][dim]))
            positions[particle_idx] = _normalize_vector(positions[particle_idx], network)
            score = _fitness(positions[particle_idx], network, users, relation_slice_indices)
            if score > personal_scores[particle_idx]:
                personal_scores[particle_idx] = score
                personal_best[particle_idx] = positions[particle_idx][:]
                if score > global_score:
                    global_score = score
                    global_best = positions[particle_idx][:]

    best = _normalize_vector(global_best, network)
    return {
        idx: {
            "power": round(best[idx], 5),
            "bandwidth": round(best[idx + SLICE_COUNT], 5),
        }
        for idx in range(SLICE_COUNT)
    }


def _canonical_strategy(raw: str) -> str:
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


def _build_response(
    allocations: List[UserResourceAllocation],
    network: NetworkConfig,
    strategy: str,
) -> ResourceAllocationResponseV2:
    timeline: List[Dict[str, float]] = []
    run_bw = 0.0
    run_power = 0.0
    seen_slices = set()

    if strategy == "noslice":
        run_bw = max((float(item.bandwidth) for item in allocations), default=0.0)
        run_power = max((float(item.power) for item in allocations), default=0.0)
        if allocations:
            run_bw = min(float(network.total_bandwidth), run_bw * SLICE_COUNT)
            run_power = min(float(network.total_power), run_power * SLICE_COUNT)
        for step, _ in enumerate(allocations):
            timeline.append(
                {
                    "step": float(step + 1),
                    "used_bandwidth": round(run_bw, 5),
                    "used_power": round(run_power, 5),
                    "remaining_bandwidth": round(max(0.0, float(network.total_bandwidth) - run_bw), 5),
                    "remaining_power": round(max(0.0, float(network.total_power) - run_power), 5),
                }
            )
        return ResourceAllocationResponseV2(
            allocations=allocations,
            used_resources={
                "bandwidth": round(run_bw, 5),
                "power": round(run_power, 5),
            },
            remaining_resources={
                "bandwidth": round(max(0.0, float(network.total_bandwidth) - run_bw), 5),
                "power": round(max(0.0, float(network.total_power) - run_power), 5),
            },
            timeline=timeline,
        )

    for step, item in enumerate(allocations):
        if item.slice_id not in seen_slices:
            run_bw += float(item.bandwidth)
            run_power += float(item.power)
            seen_slices.add(item.slice_id)
        timeline.append(
            {
                "step": float(step + 1),
                "used_bandwidth": round(run_bw, 5),
                "used_power": round(run_power, 5),
                "remaining_bandwidth": round(max(0.0, float(network.total_bandwidth) - run_bw), 5),
                "remaining_power": round(max(0.0, float(network.total_power) - run_power), 5),
            }
        )

    used_resources = {
        "bandwidth": round(run_bw, 5),
        "power": round(run_power, 5),
    }
    remaining_resources = {
        "bandwidth": round(max(0.0, float(network.total_bandwidth) - used_resources["bandwidth"]), 5),
        "power": round(max(0.0, float(network.total_power) - used_resources["power"]), 5),
    }

    return ResourceAllocationResponseV2(
        allocations=allocations,
        used_resources=used_resources,
        remaining_resources=remaining_resources,
        timeline=timeline,
    )


def allocate_user_resources(payload: ResourceAllocationRequestV2) -> ResourceAllocationResponseV2:
    strategy = _canonical_strategy(payload.algorithm)
    if not payload.users or not payload.relations:
        return _build_response([], payload.network, strategy)

    user_map: Dict[str, UserBusinessItem] = {user.user_id: user for user in payload.users}
    allocations: List[UserResourceAllocation] = []

    if strategy == "noslice":
        fixed = _noslice_equal_resource(payload.network)
        for relation in payload.relations:
            user = user_map.get(relation.user_id)
            if user is None:
                continue
            allocations.append(
                UserResourceAllocation(
                    user_id=user.user_id,
                    slice_id=relation.matched_slice_id,
                    bandwidth=round(fixed["bandwidth"], 8),
                    power=round(fixed["power"], 10),
                )
            )
        return _build_response(allocations, payload.network, strategy)

    resource_table = _pso_slice_resource_table(payload.users, payload.relations, payload.network)

    for relation in payload.relations:
        user = user_map.get(relation.user_id)
        if user is None:
            continue
        slice_idx = _slice_index_from_id(relation.matched_slice_id)
        resources = resource_table[slice_idx]
        allocations.append(
            UserResourceAllocation(
                user_id=user.user_id,
                slice_id=relation.matched_slice_id,
                bandwidth=resources["bandwidth"],
                power=resources["power"],
            )
        )

    return _build_response(allocations, payload.network, strategy)
