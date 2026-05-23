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
OLD_NOISE_DBM = -114.45
OLD_DISTANCE_M = 3000.0
DEFAULT_TARGET_SNR_DB = 6.0
DEFAULT_CHANNEL_SCENARIO = "target_snr"
CHANNEL_SCENARIOS = {
    # 按目标 SNR 离散配置（-6 dB 到 12 dB）
    "snr_m6": {"noise_dbm": -104.5, "distance_factor": 1.15, "delay_ref_ms": 1.40},
    "snr_m4": {"noise_dbm": -106.5, "distance_factor": 1.15, "delay_ref_ms": 1.30},
    "snr_m2": {"noise_dbm": -108.5, "distance_factor": 1.15, "delay_ref_ms": 1.20},
    "snr_0": {"noise_dbm": -110.5, "distance_factor": 1.15, "delay_ref_ms": 1.10},
    "snr_2": {"noise_dbm": -112.5, "distance_factor": 1.15, "delay_ref_ms": 1.00},
    "snr_4": {"noise_dbm": OLD_NOISE_DBM, "distance_factor": 1.0, "delay_ref_ms": 0.90},
    "snr_6": {"noise_dbm": -116.5, "distance_factor": 1.15, "delay_ref_ms": 0.82},
    "snr_8": {"noise_dbm": -118.5, "distance_factor": 1.15, "delay_ref_ms": 0.76},
    "snr_10": {"noise_dbm": -120.5, "distance_factor": 1.15, "delay_ref_ms": 0.70},
    "snr_12": {"noise_dbm": -122.5, "distance_factor": 1.15, "delay_ref_ms": 0.64},
}
PKL_TO_VOCAB = {
    "test_data_en.pkl": "vocab_en.json",
    "test_data-en90%.pkl": "vocab_en90%.json",
    "test_data-en80%.pkl": "vocab_en80%.json",
}
VOCAB_BASE_SIMILARITY = {
    "vocab_en.json": 0.74,
    "vocab_en90%.json": 0.71,
    "vocab_en80%.json": 0.69,
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
    results: List[SemanticResultItem] = []
    for service in services:
        encoder_level = select_encoder_level(service.semantic_nssai)

        power_share = max(0.02, min(0.5, service.request_bandwidth / max(total_request_bw, 1e-9)))
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


def _normalize_vocab_name(task_vocab: str, task_pkl: str) -> str:
    vocab = str(task_vocab or "").strip()
    if vocab:
        return vocab
    pkl_name = str(task_pkl or "").strip()
    return PKL_TO_VOCAB.get(pkl_name, "vocab_en.json")


def _resolve_base_similarity(task_vocab: str, task_pkl: str, base_similarity: float) -> float:
    vocab_name = _normalize_vocab_name(task_vocab, task_pkl)
    if vocab_name in VOCAB_BASE_SIMILARITY:
        return float(VOCAB_BASE_SIMILARITY[vocab_name])
    return float(base_similarity)


def _auto_users_from_business(config: BusinessConfig) -> List[UserBusinessItem]:
    req_types = ["high_fidelity", "low_latency"]
    task_profiles = [
        ("test_data_en.pkl", "vocab_en.json"),
        ("test_data-en90%.pkl", "vocab_en90%.json"),
        ("test_data-en80%.pkl", "vocab_en80%.json"),
    ]
    users: List[UserBusinessItem] = []
    for idx in range(config.user_count):
        req_type = config.default_requirement_type if config.default_requirement_type in req_types else req_types[idx % 2]
        task_pkl, task_vocab = task_profiles[idx % len(task_profiles)]
        base_similarity = _resolve_base_similarity(task_vocab, task_pkl, 0.72)
        users.append(
            UserBusinessItem(
                user_id="user-{0}".format(idx + 1),
                modality="text",
                requirement_type=req_type,
                domain_type="generic",
                payload_symbols=RANDOM.randint(8, 18),
                distance_m=RANDOM.uniform(1500.0, 4000.0),
                base_similarity=base_similarity,
                task_pkl=task_pkl,
                task_vocab=task_vocab,
                sample_index=idx,
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
                modality="text",
                requirement_type=user.requirement_type,
                domain_type=user.domain_type,
                payload_symbols=user.payload_symbols,
                distance_m=user.distance_m,
                base_similarity=_resolve_base_similarity(user.task_vocab, user.task_pkl, user.base_similarity),
                task_pkl=user.task_pkl,
                task_vocab=user.task_vocab,
                sample_index=int(getattr(user, "sample_index", 0)),
            )
        )

    summary = {
        "user_count": len(normalized_users),
        "modality": "text",
        "high_fidelity_count": sum(1 for user in normalized_users if user.requirement_type == "high_fidelity"),
        "low_latency_count": sum(1 for user in normalized_users if user.requirement_type == "low_latency"),
    }
    return BusinessConfigResponse(users=normalized_users, summary=summary)


def build_network_config(network: NetworkConfig) -> NetworkConfigResponse:
    normalized = {
        "total_bandwidth": float(network.total_bandwidth),
        "total_power": float(network.total_power),
        "target_snr_db": float(network.target_snr_db),
        "node_count": int(network.node_count),
        "base_station_count": int(network.base_station_count),
        "noise_dbm": OLD_NOISE_DBM,
        "distance_m": OLD_DISTANCE_M,
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
        distance_m=OLD_DISTANCE_M,
        noise_dbm=noise_dbm,
    )
    delay_ms = transmit_delay_ms(user.payload_symbols, 30, max(1e-6, allocation.bandwidth), snr_db)
    encoder_level = 1
    slice_token = str(allocation.slice_id or "").lower()
    if slice_token.endswith("2") or "90" in slice_token:
        encoder_level = 2
    elif slice_token.endswith("3") or "80" in slice_token:
        encoder_level = 3
    fidelity = _estimate_fidelity(user.base_similarity, snr_db, encoder_level, delay_ms)
    return {
        "snr_db": round(snr_db, 4),
        "delay_ms": round(delay_ms, 4),
        "fidelity": round(fidelity, 4),
    }
