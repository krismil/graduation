from collections import defaultdict
from typing import Dict, List

import numpy as np

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
from app.services.legacy_adapter import evaluate_legacy_vector
from app.services.semantic_service import CHANNEL_SCENARIOS, semantic_metrics_for_user


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
                "compute": network_state.total_compute,
            },
        )

    service_map = {service.service_id: service for service in services}

    demand_bw: Dict[str, float] = defaultdict(float)
    demand_compute: Dict[str, float] = defaultdict(float)
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
            demand_compute[slice_info.slice_id] += service.request_compute
            nssai_values.append(service.semantic_nssai)
            types.append(service.task_type)

        avg_nssai[slice_info.slice_id] = sum(nssai_values) / max(len(nssai_values), 1)
        task_types[slice_info.slice_id] = types

    raw_scores: Dict[str, float] = {}
    for slice_info in slices:
        sid = slice_info.slice_id
        weight = _slice_weight(task_types[sid], avg_nssai[sid], network_state.congestion_level)
        raw_scores[sid] = (demand_bw[sid] + 0.1 * demand_compute[sid]) * weight

    total_score = sum(raw_scores.values()) or 1.0

    min_share = 0.05
    allocations: List[ResourceAllocationItem] = []

    used_power = 0.0
    used_bandwidth = 0.0
    used_compute = 0.0

    for slice_info in slices:
        sid = slice_info.slice_id
        ratio = raw_scores[sid] / total_score
        ratio = max(min_share, ratio)

        power = network_state.total_power * ratio
        bandwidth = network_state.total_bandwidth * ratio
        compute = network_state.total_compute * ratio

        allocations.append(
            ResourceAllocationItem(
                slice_id=sid,
                power=round(power, 5),
                bandwidth=round(bandwidth, 5),
                compute=round(compute, 5),
            )
        )

        used_power += power
        used_bandwidth += bandwidth
        used_compute += compute

    if allocations:
        scale_power = network_state.total_power / used_power
        scale_bandwidth = network_state.total_bandwidth / used_bandwidth
        scale_compute = network_state.total_compute / used_compute

        for item in allocations:
            item.power = round(item.power * scale_power, 5)
            item.bandwidth = round(item.bandwidth * scale_bandwidth, 5)
            item.compute = round(item.compute * scale_compute, 5)

    remaining = {
        "power": round(network_state.total_power - sum(item.power for item in allocations), 6),
        "bandwidth": round(network_state.total_bandwidth - sum(item.bandwidth for item in allocations), 6),
        "compute": round(network_state.total_compute - sum(item.compute for item in allocations), 6),
    }

    return OrchestrationResponse(allocations=allocations, remaining=remaining)


def _base_weight(requirement_type: str, similarity_score: float, algorithm: str) -> float:
    if algorithm == "equal":
        return 1.0
    if algorithm == "latency_first":
        return 2.2 if requirement_type == "low_latency" else 1.0
    return (1.2 if requirement_type == "high_fidelity" else 1.4) * (0.8 + similarity_score)


def _energy_cost(compute: float, power: float) -> float:
    return 1.8 * compute + 45.0 * power


def _build_response(allocations: List[UserResourceAllocation], network: NetworkConfig) -> ResourceAllocationResponseV2:
    timeline: List[Dict[str, float]] = []

    run_bw = 0.0
    run_power = 0.0
    run_compute = 0.0
    run_energy = 0.0

    for step, item in enumerate(allocations):
        run_bw += item.bandwidth
        run_power += item.power
        run_compute += item.compute
        run_energy += item.energy_cost
        timeline.append(
            {
                "step": float(step + 1),
                "used_bandwidth": round(run_bw, 5),
                "used_power": round(run_power, 5),
                "used_compute": round(run_compute, 5),
                "used_energy": round(run_energy, 5),
                "remaining_bandwidth": round(max(0.0, network.total_bandwidth - run_bw), 5),
                "remaining_power": round(max(0.0, network.total_power - run_power), 5),
                "remaining_compute": round(max(0.0, network.cpu_capacity - run_compute), 5),
                "remaining_energy": round(max(0.0, network.compute_energy_threshold - run_energy), 5),
            }
        )

    used_resources = {
        "bandwidth": round(sum(item.bandwidth for item in allocations), 5),
        "power": round(sum(item.power for item in allocations), 5),
        "compute": round(sum(item.compute for item in allocations), 5),
        "energy": round(sum(item.energy_cost for item in allocations), 5),
    }
    remaining_resources = {
        "bandwidth": round(max(0.0, network.total_bandwidth - used_resources["bandwidth"]), 5),
        "power": round(max(0.0, network.total_power - used_resources["power"]), 5),
        "compute": round(max(0.0, network.cpu_capacity - used_resources["compute"]), 5),
        "energy": round(max(0.0, network.compute_energy_threshold - used_resources["energy"]), 5),
    }

    return ResourceAllocationResponseV2(
        allocations=allocations,
        used_resources=used_resources,
        remaining_resources=remaining_resources,
        timeline=timeline,
    )


def _allocate_user_resources_simple(payload: ResourceAllocationRequestV2) -> ResourceAllocationResponseV2:
    users = payload.users
    relations = payload.relations
    network = payload.network

    if not users or not relations:
        return _build_response([], network)

    user_map: Dict[str, UserBusinessItem] = {user.user_id: user for user in users}

    weighted_rows = []
    for rel in relations:
        user = user_map.get(rel.user_id)
        if not user:
            continue
        weight = _base_weight(user.requirement_type, rel.similarity_score, payload.algorithm)
        weighted_rows.append((rel, user, weight))

    total_weight = sum(item[2] for item in weighted_rows) or 1.0

    allocations: List[UserResourceAllocation] = []

    used_bw = 0.0
    used_power = 0.0
    used_compute = 0.0

    for rel, user, weight in weighted_rows:
        ratio = weight / total_weight
        alloc_bw = max(0.01, network.total_bandwidth * ratio)
        alloc_power = max(0.005, network.total_power * ratio)
        alloc_compute = max(0.5, network.cpu_capacity * ratio)

        allocations.append(
            UserResourceAllocation(
                user_id=user.user_id,
                tenant_id=user.tenant_id,
                slice_id=rel.matched_slice_id,
                bandwidth=round(alloc_bw, 5),
                power=round(alloc_power, 5),
                compute=round(alloc_compute, 5),
                energy_cost=0.0,
            )
        )

        used_bw += alloc_bw
        used_power += alloc_power
        used_compute += alloc_compute

    scale_bw = network.total_bandwidth / used_bw if used_bw else 1.0
    scale_power = network.total_power / used_power if used_power else 1.0
    scale_compute = network.cpu_capacity / used_compute if used_compute else 1.0

    used_energy = 0.0
    for item in allocations:
        item.bandwidth = round(item.bandwidth * scale_bw, 5)
        item.power = round(item.power * scale_power, 5)
        item.compute = round(item.compute * scale_compute, 5)
        item.energy_cost = round(_energy_cost(item.compute, item.power), 5)
        used_energy += item.energy_cost

    if used_energy > network.compute_energy_threshold and used_energy > 0:
        factor = network.compute_energy_threshold / used_energy
        for item in allocations:
            item.compute = round(item.compute * factor, 5)
            item.energy_cost = round(_energy_cost(item.compute, item.power), 5)

    return _build_response(allocations, network)


class _PSOAllocator(object):
    def __init__(self, payload: ResourceAllocationRequestV2):
        self.payload = payload
        self.users = payload.users
        self.relations = payload.relations
        self.network = payload.network

        self.user_map = dict((user.user_id, user) for user in self.users)
        self.rel_map = dict((rel.user_id, rel) for rel in self.relations)

        self.n = len(self.users)
        self.dimension = self.n * 3
        self.size = min(20, max(6, self.n * 3))
        self.time = 18
        self.v_low = -0.1
        self.v_high = 0.1

        self.low = np.array(([0.01] * self.n) + ([0.001] * self.n) + ([0.1] * self.n), dtype=float)
        self.up = np.array(
            ([self.network.total_bandwidth] * self.n)
            + ([self.network.total_power] * self.n)
            + ([self.network.cpu_capacity] * self.n),
            dtype=float,
        )

        self.x = np.random.uniform(0.01, 0.9, (self.size, self.dimension))
        self.v = np.zeros((self.size, self.dimension), dtype=float)

        self.p_best = np.copy(self.x)
        self.p_best_fitness = np.array([-1e18 for _ in range(self.size)], dtype=float)

        self.g_best = np.copy(self.x[0])
        self.g_best_fitness = -1e18
        self.best_allocations = []

        profile = CHANNEL_SCENARIOS.get(self.network.channel_scenario, CHANNEL_SCENARIOS["factory_indoor"])
        self.noise_dbm = float(profile["noise_dbm"])
        self.distance_factor = float(profile["distance_factor"])

        for i in range(self.size):
            self.x[i] = np.random.uniform(self.low, self.up)
            self.v[i] = np.random.uniform(self.v_low, self.v_high, self.dimension)
            fitness, allocations = self.fitness(self.x[i])
            self.p_best[i] = np.copy(self.x[i])
            self.p_best_fitness[i] = fitness
            if fitness > self.g_best_fitness:
                self.g_best_fitness = fitness
                self.g_best = np.copy(self.x[i])
                self.best_allocations = allocations

    def _normalize(self, x: np.ndarray):
        n = self.n
        bw = np.clip(np.array(x[:n], dtype=float), 1e-4, None)
        power = np.clip(np.array(x[n : 2 * n], dtype=float), 1e-6, None)
        compute = np.clip(np.array(x[2 * n :], dtype=float), 1e-3, None)

        if bw.sum() > self.network.total_bandwidth:
            bw = bw * (self.network.total_bandwidth / bw.sum())
        if power.sum() > self.network.total_power:
            power = power * (self.network.total_power / power.sum())
        if compute.sum() > self.network.cpu_capacity:
            compute = compute * (self.network.cpu_capacity / compute.sum())

        return bw, power, compute

    def _build_allocations(self, bw, power, compute):
        allocations = []
        for idx, user in enumerate(self.users):
            rel = self.rel_map.get(user.user_id)
            slice_id = rel.matched_slice_id if rel is not None else "slice-1"
            item = UserResourceAllocation(
                user_id=user.user_id,
                tenant_id=user.tenant_id,
                slice_id=slice_id,
                bandwidth=round(float(bw[idx]), 5),
                power=round(float(power[idx]), 5),
                compute=round(float(compute[idx]), 5),
                energy_cost=0.0,
            )
            item.energy_cost = round(_energy_cost(item.compute, item.power), 5)
            allocations.append(item)
        return allocations

    def fitness(self, x: np.ndarray):
        bw, power, compute = self._normalize(x)
        allocations = self._build_allocations(bw, power, compute)

        total_energy = sum(item.energy_cost for item in allocations)
        if total_energy > self.network.compute_energy_threshold and total_energy > 0:
            factor = self.network.compute_energy_threshold / total_energy
            compute = compute * factor
            allocations = self._build_allocations(bw, power, compute)

        utilities = []
        penalty = 0.0

        for item in allocations:
            user = self.user_map[item.user_id]
            rel = self.rel_map.get(item.user_id)
            similarity = rel.similarity_score if rel is not None else 0.6
            metric = semantic_metrics_for_user(user, item, self.noise_dbm, self.distance_factor)
            delay_ms = metric["delay_ms"]
            fidelity = metric["fidelity"]

            if user.requirement_type == "low_latency":
                utility = 0.65 * (1.0 / (1.0 + delay_ms / 130.0)) + 0.35 * fidelity
                if delay_ms <= 130.0:
                    utility += 0.05
                else:
                    penalty += 0.02 * ((delay_ms - 130.0) / 130.0)
            else:
                utility = 0.75 * fidelity + 0.25 * (1.0 / (1.0 + delay_ms / 220.0))
                if fidelity >= 0.6:
                    utility += 0.05
                else:
                    penalty += 0.04 * (0.6 - fidelity)

            utility = utility * (0.7 + 0.3 * similarity)
            utilities.append(utility)

        if not utilities:
            return -1e9, []

        fairness = min(utilities)
        avg_utility = sum(utilities) / len(utilities)
        score = avg_utility + 0.15 * fairness - penalty
        return score, allocations

    def update(self, size: int, c1: float, c2: float, w: float):
        for i in range(size):
            r1 = np.random.uniform(0, 1, self.dimension)
            r2 = np.random.uniform(0, 1, self.dimension)
            self.v[i] = w * self.v[i] + c1 * r1 * (self.p_best[i] - self.x[i]) + c2 * r2 * (self.g_best - self.x[i])
            self.v[i] = np.clip(self.v[i], self.v_low, self.v_high)

            self.x[i] = self.x[i] + self.v[i]
            self.x[i] = np.clip(self.x[i], self.low, self.up)

            current_fitness, allocations = self.fitness(self.x[i])

            if current_fitness > self.p_best_fitness[i]:
                self.p_best[i] = np.copy(self.x[i])
                self.p_best_fitness[i] = current_fitness

            if current_fitness > self.g_best_fitness:
                self.g_best = np.copy(self.x[i])
                self.g_best_fitness = current_fitness
                self.best_allocations = allocations

    def run(self):
        for gen in range(self.time):
            c1 = 1.5 + np.sin(np.pi / 2 * (1 - (2 * gen / self.time)))
            c2 = 1.5 + np.sin(np.pi / 2 * ((2 * gen / self.time) - 1))
            w = 1.6 - 1.2 * gen / self.time
            self.update(self.size, c1, c2, w)

        if not self.best_allocations:
            _, self.best_allocations = self.fitness(self.g_best)
        return self.best_allocations


def _allocate_user_resources_pso(payload: ResourceAllocationRequestV2) -> ResourceAllocationResponseV2:
    if not payload.users or not payload.relations:
        return _build_response([], payload.network)

    allocator = _PSOAllocator(payload)
    allocations = allocator.run()
    return _build_response(allocations, payload.network)


def _normalize_legacy_vector(payload: ResourceAllocationRequestV2, vector: np.ndarray) -> np.ndarray:
    x = np.array(vector, dtype=float)
    x = np.clip(x, 1e-6, None)

    power = x[:3]
    bandwidth = x[3:]

    total_power = power.sum()
    total_bandwidth = bandwidth.sum()

    if total_power > payload.network.total_power:
        power = power * (payload.network.total_power / total_power)
    if total_bandwidth > payload.network.total_bandwidth:
        bandwidth = bandwidth * (payload.network.total_bandwidth / total_bandwidth)

    return np.concatenate([power, bandwidth])


def _legacy_slice_index_map(payload: ResourceAllocationRequestV2) -> Dict[str, int]:
    slice_order = []
    for rel in payload.relations:
        if rel.matched_slice_id not in slice_order:
            slice_order.append(rel.matched_slice_id)

    mapping = {}
    for idx, slice_id in enumerate(slice_order):
        mapping[slice_id] = idx % 3
    return mapping


def _build_allocations_from_legacy_vector(payload: ResourceAllocationRequestV2, vector: np.ndarray) -> List[UserResourceAllocation]:
    x = _normalize_legacy_vector(payload, vector)
    power_slices = x[:3]
    bandwidth_slices = x[3:]

    rel_map = {rel.user_id: rel for rel in payload.relations}
    user_groups: Dict[int, List[UserBusinessItem]] = {0: [], 1: [], 2: []}

    slice_map = _legacy_slice_index_map(payload)
    for user in payload.users:
        rel = rel_map.get(user.user_id)
        if rel is None:
            idx = 0
        else:
            idx = slice_map.get(rel.matched_slice_id, 0)
        user_groups[idx].append(user)

    allocations: List[UserResourceAllocation] = []
    total_compute = payload.network.cpu_capacity

    for idx in range(3):
        users = user_groups[idx]
        if not users:
            continue

        slice_power = float(power_slices[idx])
        slice_bandwidth = float(bandwidth_slices[idx])
        slice_compute = total_compute * (slice_power / max(payload.network.total_power, 1e-9))

        weights = []
        for user in users:
            rel = rel_map.get(user.user_id)
            similarity = rel.similarity_score if rel is not None else 0.6
            req_weight = 1.4 if user.requirement_type == "low_latency" else 1.2
            weights.append(max(1e-6, req_weight * (0.7 + 0.3 * similarity)))

        total_weight = sum(weights)
        for user, weight in zip(users, weights):
            ratio = weight / total_weight
            rel = rel_map.get(user.user_id)
            slice_id = rel.matched_slice_id if rel is not None else "slice-1"
            item = UserResourceAllocation(
                user_id=user.user_id,
                tenant_id=user.tenant_id,
                slice_id=slice_id,
                bandwidth=round(slice_bandwidth * ratio, 5),
                power=round(slice_power * ratio, 5),
                compute=round(slice_compute * ratio, 5),
                energy_cost=0.0,
            )
            item.energy_cost = round(_energy_cost(item.compute, item.power), 5)
            allocations.append(item)

    total_energy = sum(item.energy_cost for item in allocations)
    if total_energy > payload.network.compute_energy_threshold and total_energy > 0:
        factor = payload.network.compute_energy_threshold / total_energy
        for item in allocations:
            item.compute = round(item.compute * factor, 5)
            item.energy_cost = round(_energy_cost(item.compute, item.power), 5)

    return allocations


def _legacy_fitness(payload: ResourceAllocationRequestV2, vector: np.ndarray) -> float:
    normalized = _normalize_legacy_vector(payload, vector)
    legacy_vector = [float(normalized[0]), float(normalized[1]), float(normalized[2]), float(normalized[3]), float(normalized[4]), float(normalized[5])]

    score_sum, _, _ = evaluate_legacy_vector(payload.legacy_strategy, payload.legacy_scenario, legacy_vector)

    allocations = _build_allocations_from_legacy_vector(payload, normalized)
    total_energy = sum(item.energy_cost for item in allocations)

    penalty = 0.0
    if total_energy > payload.network.compute_energy_threshold:
        penalty += (total_energy - payload.network.compute_energy_threshold) / max(payload.network.compute_energy_threshold, 1.0)

    profile = CHANNEL_SCENARIOS.get(payload.network.channel_scenario, CHANNEL_SCENARIOS["factory_indoor"])
    noise_dbm = float(profile["noise_dbm"])
    distance_factor = float(profile["distance_factor"])
    user_map = {user.user_id: user for user in payload.users}

    metric_bonus = 0.0
    for item in allocations:
        user = user_map.get(item.user_id)
        if user is None:
            continue
        metric = semantic_metrics_for_user(user, item, noise_dbm, distance_factor)
        if user.requirement_type == "low_latency":
            metric_bonus += max(0.0, 1.0 - metric["delay_ms"] / 150.0)
        else:
            metric_bonus += metric["fidelity"]

    metric_bonus = metric_bonus / max(len(allocations), 1)
    return float(score_sum + 0.3 * metric_bonus - 0.2 * penalty)


def _run_legacy_pso(payload: ResourceAllocationRequestV2) -> np.ndarray:
    dimension = 6
    size = max(2, int(payload.legacy_particles))
    time = max(1, int(payload.legacy_iterations))
    v_low = -0.1
    v_high = 0.1

    low = np.array([
        max(1e-4, payload.network.total_power * 0.001),
        max(1e-4, payload.network.total_power * 0.001),
        max(1e-4, payload.network.total_power * 0.001),
        max(1e-4, payload.network.total_bandwidth * 0.001),
        max(1e-4, payload.network.total_bandwidth * 0.001),
        max(1e-4, payload.network.total_bandwidth * 0.001),
    ], dtype=float)

    up = np.array([
        max(0.1, payload.network.total_power),
        max(0.1, payload.network.total_power),
        max(0.1, payload.network.total_power),
        max(0.1, payload.network.total_bandwidth),
        max(0.1, payload.network.total_bandwidth),
        max(0.1, payload.network.total_bandwidth),
    ], dtype=float)

    x = np.random.uniform(low, up, (size, dimension))
    v = np.random.uniform(v_low, v_high, (size, dimension))

    p_best = np.copy(x)
    p_best_fitness = np.array([-1e18 for _ in range(size)], dtype=float)

    g_best = np.copy(x[0])
    g_best_fitness = -1e18

    for i in range(size):
        fitness = _legacy_fitness(payload, x[i])
        p_best_fitness[i] = fitness
        if fitness > g_best_fitness:
            g_best_fitness = fitness
            g_best = np.copy(x[i])

    for gen in range(time):
        c1 = 1.5 + np.sin(np.pi / 2 * (1 - (2 * gen / max(time, 1))))
        c2 = 1.5 + np.sin(np.pi / 2 * ((2 * gen / max(time, 1)) - 1))
        w = 1.6 - 1.2 * gen / max(time, 1)

        for i in range(size):
            r1 = np.random.uniform(0, 1, dimension)
            r2 = np.random.uniform(0, 1, dimension)
            v[i] = w * v[i] + c1 * r1 * (p_best[i] - x[i]) + c2 * r2 * (g_best - x[i])
            v[i] = np.clip(v[i], v_low, v_high)

            x[i] = x[i] + v[i]
            x[i] = np.clip(x[i], low, up)

            current_fitness = _legacy_fitness(payload, x[i])
            if current_fitness > p_best_fitness[i]:
                p_best[i] = np.copy(x[i])
                p_best_fitness[i] = current_fitness
            if current_fitness > g_best_fitness:
                g_best = np.copy(x[i])
                g_best_fitness = current_fitness

    return _normalize_legacy_vector(payload, g_best)


def _allocate_user_resources_legacy_experiment(payload: ResourceAllocationRequestV2) -> ResourceAllocationResponseV2:
    if not payload.users or not payload.relations:
        return _build_response([], payload.network)

    best_vector = _run_legacy_pso(payload)
    allocations = _build_allocations_from_legacy_vector(payload, best_vector)
    return _build_response(allocations, payload.network)


def allocate_user_resources(payload: ResourceAllocationRequestV2) -> ResourceAllocationResponseV2:
    if payload.allocation_backend == "legacy_experiment":
        return _allocate_user_resources_legacy_experiment(payload)
    if payload.algorithm == "pso":
        return _allocate_user_resources_pso(payload)
    return _allocate_user_resources_simple(payload)


