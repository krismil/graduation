import math
import random
from statistics import mean
from typing import Dict, List

from app.models.schemas import (
    BusinessConfig,
    BusinessConfigResponse,
    NetworkConfig,
    NetworkConfigResponse,
    SemanticProcessResponse,
    SemanticResultItem,
    ServiceProfile,
    UserBusinessItem,
    UserResourceAllocation,
)


RANDOM = random.Random(2026)
CHANNEL_SCENARIOS = {
    "factory_indoor": {"noise_dbm": -106.0, "distance_factor": 0.85, "delay_ref_ms": 0.90},
    "satellite_link": {"noise_dbm": -118.0, "distance_factor": 1.8, "delay_ref_ms": 1.30},
    "urban_macro": {"noise_dbm": -110.5, "distance_factor": 1.15, "delay_ref_ms": 1.00},
    # 便于按“信道类型=目标SNR”方式做曲线验证（-6dB 到 12dB）
    "snr_m6": {"noise_dbm": -104.5, "distance_factor": 1.15, "delay_ref_ms": 1.40},
    "snr_m4": {"noise_dbm": -106.5, "distance_factor": 1.15, "delay_ref_ms": 1.30},
    "snr_m2": {"noise_dbm": -108.5, "distance_factor": 1.15, "delay_ref_ms": 1.20},
    "snr_0": {"noise_dbm": -110.5, "distance_factor": 1.15, "delay_ref_ms": 1.10},
    "snr_2": {"noise_dbm": -112.5, "distance_factor": 1.15, "delay_ref_ms": 1.00},
    "snr_4": {"noise_dbm": -114.5, "distance_factor": 1.15, "delay_ref_ms": 0.90},
    "snr_6": {"noise_dbm": -116.5, "distance_factor": 1.15, "delay_ref_ms": 0.82},
    "snr_8": {"noise_dbm": -118.5, "distance_factor": 1.15, "delay_ref_ms": 0.76},
    "snr_10": {"noise_dbm": -120.5, "distance_factor": 1.15, "delay_ref_ms": 0.70},
    "snr_12": {"noise_dbm": -122.5, "distance_factor": 1.15, "delay_ref_ms": 0.64},
}
DOMAIN_BASE_SIMILARITY = {
    "animal": 0.74,
    "music": 0.71,
    "sports": 0.69,
}


def select_encoder_level(semantic_nssai: float) -> int:
    if semantic_nssai >= 95:
        return 1
    if semantic_nssai >= 85:
        return 2
    return 3


def compute_snr_db(power: float, bandwidth_mhz: float, distance_m: float, noise_dbm: float) -> float:
    n0 = (10 ** (noise_dbm / 10)) * 1e-3
    snr_linear = power / (bandwidth_mhz * 1e6 * (distance_m ** 2) * n0)
    snr_linear = max(snr_linear, 1e-9)
    return 10 * math.log10(snr_linear)


def transmit_delay_ms(payload_symbols: int, length_per_symbol: int, bandwidth_mhz: float, snr_db: float) -> float:
    snr_linear = 10 ** (snr_db / 10)
    capacity = bandwidth_mhz * 1e6 * math.log2(1 + snr_linear)
    delay_sec = payload_symbols * length_per_symbol / max(capacity, 1e-9)
    return delay_sec * 1e3


def _estimate_fidelity(base_similarity: float, snr_db: float, encoder_level: int, delay_ms: float) -> float:
    snr_gain = 0.018 * (snr_db - 3.0)
    encoder_gain = {1: 0.08, 2: 0.04, 3: 0.01}[encoder_level]
    delay_penalty = max(0.0, (delay_ms - 130) / 1300)
    fidelity = base_similarity + snr_gain + encoder_gain - delay_penalty
    return float(max(0.0, min(1.0, fidelity)))


def process_services(services: List[ServiceProfile], noise_dbm: float) -> SemanticProcessResponse:
    if not services:
        return SemanticProcessResponse(items=[], summary={"avg_fidelity": 0.0, "avg_delay_ms": 0.0, "avg_snr_db": 0.0})

    total_request_bw = sum(service.request_bandwidth for service in services)
    total_request_compute = sum(service.request_compute for service in services)

    results: List[SemanticResultItem] = []
    for service in services:
        encoder_level = select_encoder_level(service.semantic_nssai)

        power_share = max(0.02, min(0.5, service.request_compute / max(total_request_compute, 1e-9)))
        bandwidth_share = max(0.05, min(1.5, 2.0 * service.request_bandwidth / max(total_request_bw, 1e-9)))

        snr_db = compute_snr_db(
            power=power_share,
            bandwidth_mhz=bandwidth_share,
            distance_m=service.distance_m,
            noise_dbm=noise_dbm,
        )
        delay_ms = transmit_delay_ms(service.payload_symbols, 30, bandwidth_share, snr_db)
        fidelity = _estimate_fidelity(service.base_similarity, snr_db, encoder_level, delay_ms)

        results.append(
            SemanticResultItem(
                service_id=service.service_id,
                encoder_level=encoder_level,
                snr_db=round(snr_db, 4),
                semantic_fidelity=round(fidelity, 4),
                tx_delay_ms=round(delay_ms, 4),
            )
        )

    summary = {
        "avg_fidelity": round(mean(item.semantic_fidelity for item in results), 4),
        "avg_delay_ms": round(mean(item.tx_delay_ms for item in results), 4),
        "avg_snr_db": round(mean(item.snr_db for item in results), 4),
    }
    return SemanticProcessResponse(items=results, summary=summary)


def _auto_users_from_business(config: BusinessConfig) -> List[UserBusinessItem]:
    req_types = ["high_fidelity", "low_latency"]
    domains = ["animal", "music", "sports"]
    users: List[UserBusinessItem] = []
    for idx in range(config.user_count):
        req_type = config.default_requirement_type if config.default_requirement_type in req_types else req_types[idx % 2]
        domain = config.default_domain_type if config.default_domain_type in domains else domains[idx % 3]
        users.append(
            UserBusinessItem(
                user_id="user-{0}".format(idx + 1),
                tenant_id=config.tenant_id,
                modality="text",
                requirement_type=req_type,
                domain_type=domain,
                payload_symbols=RANDOM.randint(8, 18),
                distance_m=RANDOM.uniform(1500.0, 4000.0),
                base_similarity=DOMAIN_BASE_SIMILARITY.get(domain, 0.68),
            )
        )
    return users


def build_business_config(config: BusinessConfig) -> BusinessConfigResponse:
    users = config.users if config.users else _auto_users_from_business(config)
    normalized_users = []
    for user in users:
        normalized_users.append(
            UserBusinessItem(
                user_id=user.user_id,
                tenant_id=user.tenant_id or config.tenant_id,
                modality="text",
                requirement_type=user.requirement_type,
                domain_type=user.domain_type,
                payload_symbols=user.payload_symbols,
                distance_m=user.distance_m,
                base_similarity=user.base_similarity,
            )
        )

    summary = {
        "user_count": len(normalized_users),
        "modality": "text",
        "tenant_id": config.tenant_id,
        "high_fidelity_count": sum(1 for user in normalized_users if user.requirement_type == "high_fidelity"),
        "low_latency_count": sum(1 for user in normalized_users if user.requirement_type == "low_latency"),
    }
    return BusinessConfigResponse(users=normalized_users, summary=summary)


def build_network_config(network: NetworkConfig) -> NetworkConfigResponse:
    profile = CHANNEL_SCENARIOS.get(network.channel_scenario, CHANNEL_SCENARIOS["factory_indoor"])
    normalized = {
        "cpu_capacity": float(network.cpu_capacity),
        "compute_energy_threshold": float(network.compute_energy_threshold),
        "total_bandwidth": float(network.total_bandwidth),
        "total_power": float(network.total_power),
        "channel_scenario": network.channel_scenario,
        "noise_dbm": profile["noise_dbm"],
        "distance_factor": profile["distance_factor"],
    }
    return NetworkConfigResponse(network=normalized)


def semantic_metrics_for_user(
    user: UserBusinessItem,
    allocation: UserResourceAllocation,
    noise_dbm: float,
    distance_factor: float,
) -> Dict[str, float]:
    snr_db = compute_snr_db(
        power=max(1e-6, allocation.power),
        bandwidth_mhz=max(1e-6, allocation.bandwidth),
        distance_m=max(1.0, user.distance_m * distance_factor),
        noise_dbm=noise_dbm,
    )
    delay_ms = transmit_delay_ms(user.payload_symbols, 30, max(1e-6, allocation.bandwidth), snr_db)
    encoder_level = 1 if allocation.compute >= 0.8 else 2 if allocation.compute >= 0.35 else 3
    fidelity = _estimate_fidelity(user.base_similarity, snr_db, encoder_level, delay_ms)
    return {
        "snr_db": round(snr_db, 4),
        "delay_ms": round(delay_ms, 4),
        "fidelity": round(fidelity, 4),
    }
