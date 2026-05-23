#!/usr/bin/env python3
"""Legacy DeepSC semantic encode/decode demo without BERT scoring.

This script keeps the old experiment's core data path:

task submission -> semantic slice selection -> DeepSC checkpoint loading
-> semantic/channel encoding -> AWGN channel -> semantic decoding.
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import torch


DEMO_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = DEMO_ROOT.parent
DEEPSC_ROOT = PROJECT_ROOT / "DeepSC-master"

if str(DEEPSC_ROOT) not in sys.path:
    sys.path.insert(0, str(DEEPSC_ROOT))

from models.transceiver import DeepSC  # noqa: E402


SPECIAL_TOKENS = {"<PAD>", "<START>", "<END>", "<UNK>"}
OLD_TOTAL_POWER = 1.0
OLD_TOTAL_BANDWIDTH_MHZ = 2.0
OLD_DISTANCE_M = 3000.0
OLD_NOISE_DBM = -114.45
OLD_SEMANTIC_SYMBOLS = 10
OLD_SYMBOL_LENGTH = 30
OLD_SIM_THRESHOLD = 0.6
OLD_DELAY_THRESHOLD_S = 0.13
DEFAULT_SLICE_POWER = (0.02, 0.05, 0.10)
DEFAULT_SLICE_BANDWIDTH_MHZ = (0.90, 0.70, 0.40)
SLICE_CONFIG = {
    0: {
        "name": "slice-1 / enorigin",
        "model_dir": "deepsc-AWGN-enorigin_layer3",
        "profile": "full",
    },
    1: {
        "name": "slice-2 / en90%",
        "model_dir": "deepsc-AWGN-en90%_layer3",
        "profile": "en90",
    },
    2: {
        "name": "slice-3 / en80%",
        "model_dir": "deepsc-AWGN-en80%_layer3",
        "profile": "en80",
    },
}
TASK_ASSETS = {
    "full": {
        "label": "full vocabulary task",
        "vocab": "vocab_en.json",
        "data": "test_data_en.pkl",
    },
    "en90": {
        "label": "90% vocabulary task",
        "vocab": "vocab_en90%.json",
        "data": "test_data-en90%.pkl",
    },
    "en80": {
        "label": "80% vocabulary task",
        "vocab": "vocab_en80%.json",
        "data": "test_data-en80%.pkl",
    },
}


@dataclass(frozen=True)
class TaskSubmission:
    """Minimal task object, mirroring the old scripts' task/vocab inputs."""

    task_id: str
    profile: str
    sample_index: int

    @property
    def assets(self) -> Dict[str, str]:
        return TASK_ASSETS[self.profile]


@dataclass(frozen=True)
class StrategyPlan:
    strategy: str
    description: str
    slice_idx: int


@dataclass(frozen=True)
class LinkMetrics:
    power: float
    bandwidth_mhz: float
    snr_db: float
    noise_std: float
    capacity_mbps: float
    delay_ms: float


@dataclass(frozen=True)
class StrategyResult:
    strategy: str
    description: str
    slice_idx: int
    slice_name: str
    checkpoint_name: str
    decoded_text: str
    token_match_rate: float
    task_passed: bool
    s_se: float
    link: LinkMetrics
    source_len: int
    decoded_len: int
    shapes: Dict[str, Tuple[int, ...]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the old DeepSC semantic encode/decode path without BERT."
    )
    parser.add_argument(
        "--deepsc-root",
        type=Path,
        default=DEEPSC_ROOT,
        help="Path to the legacy DeepSC-master directory.",
    )
    parser.add_argument(
        "--task",
        choices=sorted(TASK_ASSETS),
        default="en80",
        help="Submitted task vocabulary profile.",
    )
    parser.add_argument(
        "--sample-index",
        type=int,
        default=0,
        help="Sentence index inside the selected test_data*.pkl file.",
    )
    parser.add_argument(
        "--slice-power",
        type=float,
        nargs=3,
        default=DEFAULT_SLICE_POWER,
        metavar=("P1", "P2", "P3"),
        help="Per-slice transmit power, matching the old resource vector X[:3].",
    )
    parser.add_argument(
        "--slice-bandwidth",
        type=float,
        nargs=3,
        default=DEFAULT_SLICE_BANDWIDTH_MHZ,
        metavar=("B1", "B2", "B3"),
        help="Per-slice bandwidth in MHz, matching the old resource vector X[3:].",
    )
    parser.add_argument(
        "--total-power",
        type=float,
        default=OLD_TOTAL_POWER,
        help="Old experiment total power cap.",
    )
    parser.add_argument(
        "--total-bandwidth",
        type=float,
        default=OLD_TOTAL_BANDWIDTH_MHZ,
        help="Old experiment total bandwidth cap in MHz.",
    )
    parser.add_argument(
        "--distance-m",
        type=float,
        default=OLD_DISTANCE_M,
        help="Link distance used by the old SNR formula.",
    )
    parser.add_argument(
        "--noise-dbm",
        type=float,
        default=OLD_NOISE_DBM,
        help="Noise power spectral density used by the old SNR formula.",
    )
    parser.add_argument(
        "--semantic-symbols",
        type=int,
        default=OLD_SEMANTIC_SYMBOLS,
        help="K in the old transmit delay and S-SE calculation.",
    )
    parser.add_argument(
        "--symbol-length",
        type=int,
        default=OLD_SYMBOL_LENGTH,
        help="L in the old transmit delay formula.",
    )
    parser.add_argument(
        "--requirement-type",
        choices=("high-fidelity", "low-latency"),
        default="high-fidelity",
        help="Old task gate: similarity threshold or delay threshold.",
    )
    parser.add_argument(
        "--sim-threshold",
        type=float,
        default=OLD_SIM_THRESHOLD,
        help="High-fidelity pass threshold. TokenMatch is used here instead of BERT.",
    )
    parser.add_argument(
        "--delay-threshold",
        type=float,
        default=OLD_DELAY_THRESHOLD_S,
        help="Low-latency pass threshold in seconds.",
    )
    parser.add_argument("--max-length", type=int, default=20)
    parser.add_argument("--num-layers", type=int, default=3)
    parser.add_argument("--d-model", type=int, default=128)
    parser.add_argument("--dff", type=int, default=512)
    parser.add_argument("--num-heads", type=int, default=8)
    parser.add_argument(
        "--seed",
        type=int,
        default=7,
        help="Seed reused before each strategy so the AWGN draw is comparable.",
    )
    parser.add_argument(
        "--netslice-policy",
        choices=("stable-random", "round-robin", "fixed"),
        default="fixed",
        help="Traditional NetSlice selection rule. It ignores semantic matching.",
    )
    parser.add_argument(
        "--noslice-model",
        choices=sorted(TASK_ASSETS),
        default="en90",
        help="Shared model used by the NoSlice baseline.",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
        help="Where to run the model.",
    )
    parser.add_argument(
        "--show-special-tokens",
        action="store_true",
        help="Keep <START>/<END>/<PAD> in displayed text.",
    )
    return parser.parse_args()


def resolve_device(choice: str) -> torch.device:
    if choice == "cpu":
        return torch.device("cpu")
    if choice == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("--device cuda was requested, but CUDA is not available.")
        return torch.device("cuda")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_vocab(path: Path) -> Dict[str, int]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["token_to_idx"]


def load_task_data(path: Path) -> List[List[int]]:
    with path.open("rb") as handle:
        return pickle.load(handle)


def knowledge_match(full_vocab: Dict[str, int], task_vocab: Dict[str, int]) -> float:
    full_keys = set(full_vocab.keys())
    task_keys = set(task_vocab.keys())
    return 100.0 * len(full_keys & task_keys) / len(full_keys)


def select_slice(sem_nssai: float) -> int:
    """Old SemSlice selection rule based on vocabulary overlap."""
    if sem_nssai >= 95:
        return 0
    if 85 <= sem_nssai < 95:
        return 1
    if 75 <= sem_nssai < 85:
        return 2
    raise ValueError(
        f"Knowledge match {sem_nssai:.2f}% is below the old demo's slice range."
    )


def stable_random_slice(task: TaskSubmission) -> int:
    """Deterministic stand-in for the old random NetSlice assignment."""
    key = f"{task.task_id}:{task.sample_index}:{task.profile}"
    return sum(ord(ch) for ch in key) % len(SLICE_CONFIG)


def traditional_netslice(task: TaskSubmission, policy: str) -> int:
    """Pick a network slice without looking at semantic vocabulary overlap."""
    if policy == "round-robin":
        return task.sample_index % len(SLICE_CONFIG)
    if policy == "fixed":
        return 0
    return stable_random_slice(task)


def noslice_model_to_slice(profile: str) -> int:
    for slice_idx, config in SLICE_CONFIG.items():
        if config["profile"] == profile:
            return slice_idx
    raise ValueError(f"Unknown NoSlice model profile: {profile}")


def latest_checkpoint(model_dir: Path) -> Path:
    checkpoints: List[Tuple[int, Path]] = []
    for path in model_dir.glob("*.pth"):
        match = re.search(r"_(\d+)\.pth$", path.name)
        if match:
            checkpoints.append((int(match.group(1)), path))
    if not checkpoints:
        raise FileNotFoundError(f"No checkpoint_XX.pth files found in {model_dir}")
    checkpoints.sort(key=lambda item: item[0])
    return checkpoints[-1][1]


def make_model(
    args: argparse.Namespace,
    vocab_size: int,
    checkpoint_path: Path,
    device: torch.device,
) -> DeepSC:
    model = DeepSC(
        args.num_layers,
        vocab_size,
        vocab_size,
        vocab_size,
        vocab_size,
        args.d_model,
        args.num_heads,
        args.dff,
        0.1,
    ).to(device)
    state = torch.load(checkpoint_path, map_location=device)
    model.load_state_dict(state)
    model.eval()
    return model


def snr_to_noise_std(snr_db: float) -> float:
    snr_linear = 10 ** (snr_db / 10)
    return float(1 / np.sqrt(2 * snr_linear))


def normalize_cap(values: Tuple[float, float, float], total: float) -> Tuple[float, float, float]:
    if total <= 0:
        raise ValueError("Resource total caps must be positive.")
    if any(value <= 0 for value in values):
        raise ValueError("Per-slice power and bandwidth values must be positive.")

    used = sum(values)
    if used <= total:
        return values

    scale = total / used
    return tuple(value * scale for value in values)


def normalize_slice_resources(args: argparse.Namespace) -> Tuple[Dict[int, float], Dict[int, float]]:
    power = normalize_cap(tuple(args.slice_power), args.total_power)
    bandwidth = normalize_cap(tuple(args.slice_bandwidth), args.total_bandwidth)
    return (
        {idx: value for idx, value in enumerate(power)},
        {idx: value for idx, value in enumerate(bandwidth)},
    )


def compute_snr_db(
    power: float,
    bandwidth_mhz: float,
    distance_m: float,
    noise_dbm: float,
) -> float:
    n0 = 10 ** (noise_dbm / 10) * 1e-3
    snr_linear = power / (bandwidth_mhz * 1e6 * (distance_m**2) * n0)
    if snr_linear <= 0:
        raise ValueError("Computed non-positive SNR. Check power, bandwidth, and noise.")
    return float(10 * np.log10(snr_linear))


def transmit_delay(
    semantic_symbols: int,
    symbol_length: int,
    bandwidth_mhz: float,
    snr_db: float,
) -> Tuple[float, float]:
    snr_linear = 10 ** (snr_db / 10)
    capacity_bps = bandwidth_mhz * 1e6 * math.log2(1 + snr_linear)
    if capacity_bps <= 0:
        raise ValueError("Computed non-positive capacity. Check bandwidth and SNR.")
    delay_s = semantic_symbols * symbol_length / capacity_bps
    return float(delay_s), float(capacity_bps)


def link_metrics_for_slice(
    args: argparse.Namespace,
    power: float,
    bandwidth_mhz: float,
) -> LinkMetrics:
    snr_db = compute_snr_db(
        power=power,
        bandwidth_mhz=bandwidth_mhz,
        distance_m=args.distance_m,
        noise_dbm=args.noise_dbm,
    )
    delay_s, capacity_bps = transmit_delay(
        semantic_symbols=args.semantic_symbols,
        symbol_length=args.symbol_length,
        bandwidth_mhz=bandwidth_mhz,
        snr_db=snr_db,
    )
    return LinkMetrics(
        power=power,
        bandwidth_mhz=bandwidth_mhz,
        snr_db=snr_db,
        noise_std=snr_to_noise_std(snr_db),
        capacity_mbps=capacity_bps / 1e6,
        delay_ms=delay_s * 1e3,
    )


def service_passed(
    requirement_type: str,
    token_score: float,
    delay_ms: float,
    sim_threshold: float,
    delay_threshold_s: float,
) -> bool:
    if requirement_type == "low-latency":
        return delay_ms <= delay_threshold_s * 1e3
    return token_score >= sim_threshold


def set_seed(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def power_normalize(x: torch.Tensor) -> torch.Tensor:
    power = torch.mean(torch.mul(x, x)).sqrt()
    if power > 1:
        return torch.div(x, power)
    return x


def subsequent_mask(size: int, device: torch.device) -> torch.Tensor:
    mask = np.triu(np.ones((1, size, size)), k=1).astype("uint8")
    return torch.from_numpy(mask).type(torch.float32).to(device)


def semantic_roundtrip(
    model: DeepSC,
    src: torch.Tensor,
    noise_std: float,
    max_len: int,
    pad_idx: int,
    start_idx: int,
) -> Tuple[List[int], Dict[str, Tuple[int, ...]]]:
    """Mirror old greedy_decode, but expose the intermediate tensor shapes."""
    device = src.device
    with torch.no_grad():
        src_mask = (src == pad_idx).unsqueeze(-2).type(torch.float32).to(device)

        enc_output = model.encoder(src, src_mask)
        channel_enc_output = model.channel_encoder(enc_output)
        tx_sig = power_normalize(channel_enc_output)

        rx_sig = tx_sig + torch.normal(
            mean=0.0,
            std=noise_std,
            size=tx_sig.shape,
            device=device,
        )

        memory = model.channel_decoder(rx_sig)

        outputs = torch.ones(src.size(0), 1, dtype=src.dtype, device=device)
        outputs = outputs.fill_(start_idx)

        for _ in range(max_len - 1):
            trg_mask = (outputs == pad_idx).unsqueeze(-2).type(torch.float32)
            look_ahead_mask = subsequent_mask(outputs.size(1), device)
            combined_mask = torch.max(trg_mask.to(device), look_ahead_mask)

            dec_output = model.decoder(outputs, memory, combined_mask, None)
            pred = model.dense(dec_output)
            next_word = torch.max(pred[:, -1:, :], dim=-1)[1]
            outputs = torch.cat([outputs, next_word], dim=1)

        shapes = {
            "source_tokens": tuple(src.shape),
            "semantic_encoder_output": tuple(enc_output.shape),
            "channel_encoder_output": tuple(channel_enc_output.shape),
            "tx_signal": tuple(tx_sig.shape),
            "rx_signal": tuple(rx_sig.shape),
            "channel_decoder_output": tuple(memory.shape),
            "decoded_tokens": tuple(outputs.shape),
        }
        return outputs[0].detach().cpu().tolist(), shapes


def ids_to_text(
    ids: Iterable[int],
    idx_to_token: Dict[int, str],
    keep_special_tokens: bool,
) -> str:
    words: List[str] = []
    for idx in ids:
        token = idx_to_token.get(int(idx), "<UNK>")
        if token == "<END>":
            if keep_special_tokens:
                words.append(token)
            break
        if keep_special_tokens or token not in SPECIAL_TOKENS:
            words.append(token)
    return " ".join(words)


def strip_special_ids(
    ids: Iterable[int],
    pad_idx: int,
    start_idx: int,
    end_idx: int,
) -> List[int]:
    clean: List[int] = []
    for raw_idx in ids:
        idx = int(raw_idx)
        if idx == end_idx:
            break
        if idx in (pad_idx, start_idx):
            continue
        clean.append(idx)
    return clean


def token_match_rate(source_ids: List[int], decoded_ids: List[int]) -> float:
    if not source_ids and not decoded_ids:
        return 1.0
    denom = max(len(source_ids), len(decoded_ids), 1)
    matches = sum(
        1 for left, right in zip(source_ids, decoded_ids) if int(left) == int(right)
    )
    return matches / denom


def assert_assets_exist(deepsc_root: Path, task: TaskSubmission) -> None:
    required = [
        deepsc_root / "vocab_en.json",
        deepsc_root / task.assets["vocab"],
        deepsc_root / task.assets["data"],
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        formatted = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(f"Missing required demo assets:\n{formatted}")


def run_strategy(
    args: argparse.Namespace,
    deepsc_root: Path,
    plan: StrategyPlan,
    model_cache: Dict[int, DeepSC],
    source_tensor: torch.Tensor,
    source_ids: List[int],
    idx_to_token: Dict[int, str],
    vocab_size: int,
    pad_idx: int,
    start_idx: int,
    end_idx: int,
    link: LinkMetrics,
    device: torch.device,
) -> StrategyResult:
    slice_info = SLICE_CONFIG[plan.slice_idx]
    checkpoint_path = latest_checkpoint(deepsc_root / slice_info["model_dir"])

    if plan.slice_idx not in model_cache:
        model_cache[plan.slice_idx] = make_model(
            args, vocab_size, checkpoint_path, device
        )

    set_seed(args.seed)
    decoded_ids, shapes = semantic_roundtrip(
        model=model_cache[plan.slice_idx],
        src=source_tensor,
        noise_std=link.noise_std,
        max_len=args.max_length,
        pad_idx=pad_idx,
        start_idx=start_idx,
    )
    decoded_text = ids_to_text(decoded_ids, idx_to_token, args.show_special_tokens)

    source_clean = strip_special_ids(source_ids, pad_idx, start_idx, end_idx)
    decoded_clean = strip_special_ids(decoded_ids, pad_idx, start_idx, end_idx)
    match_rate = token_match_rate(source_clean, decoded_clean)
    passed = service_passed(
        requirement_type=args.requirement_type,
        token_score=match_rate,
        delay_ms=link.delay_ms,
        sim_threshold=args.sim_threshold,
        delay_threshold_s=args.delay_threshold,
    )
    effective_score = match_rate if passed else 0.0

    return StrategyResult(
        strategy=plan.strategy,
        description=plan.description,
        slice_idx=plan.slice_idx,
        slice_name=slice_info["name"],
        checkpoint_name=checkpoint_path.name,
        decoded_text=decoded_text,
        token_match_rate=match_rate,
        task_passed=passed,
        s_se=effective_score / max(args.semantic_symbols, 1),
        link=link,
        source_len=len(source_clean),
        decoded_len=len(decoded_clean),
        shapes=shapes,
    )


def main() -> None:
    args = parse_args()
    deepsc_root = args.deepsc_root.resolve()
    task = TaskSubmission(
        task_id=f"demo-{args.task}",
        profile=args.task,
        sample_index=args.sample_index,
    )
    assert_assets_exist(deepsc_root, task)

    device = resolve_device(args.device)

    full_vocab = load_vocab(deepsc_root / "vocab_en.json")
    task_vocab = load_vocab(deepsc_root / task.assets["vocab"])
    idx_to_token = {idx: token for token, idx in full_vocab.items()}
    pad_idx = full_vocab["<PAD>"]
    start_idx = full_vocab["<START>"]
    end_idx = full_vocab["<END>"]

    sem_nssai = knowledge_match(full_vocab, task_vocab)
    semslice_idx = select_slice(sem_nssai)
    netslice_idx = traditional_netslice(task, args.netslice_policy)
    noslice_idx = noslice_model_to_slice(args.noslice_model)

    task_data = load_task_data(deepsc_root / task.assets["data"])
    if not 0 <= task.sample_index < len(task_data):
        raise IndexError(
            f"sample-index {task.sample_index} is outside 0..{len(task_data) - 1}"
        )
    source_ids = task_data[task.sample_index]
    src = torch.tensor([source_ids], dtype=torch.long, device=device)

    slice_power, slice_bandwidth = normalize_slice_resources(args)
    plans = [
        StrategyPlan(
            strategy="SemSlice",
            description="semantic vocabulary match",
            slice_idx=semslice_idx,
        ),
        StrategyPlan(
            strategy="NetSlice",
            description=f"non-semantic {args.netslice_policy}",
            slice_idx=netslice_idx,
        ),
        StrategyPlan(
            strategy="NoSlice",
            description=f"shared {args.noslice_model} model",
            slice_idx=noslice_idx,
        ),
    ]

    model_cache: Dict[int, DeepSC] = {}
    results = []
    for plan in plans:
        link = link_metrics_for_slice(
            args=args,
            power=slice_power[plan.slice_idx],
            bandwidth_mhz=slice_bandwidth[plan.slice_idx],
        )
        results.append(
            run_strategy(
                args=args,
                deepsc_root=deepsc_root,
                plan=plan,
                model_cache=model_cache,
                source_tensor=src,
                source_ids=source_ids,
                idx_to_token=idx_to_token,
                vocab_size=len(full_vocab),
                pad_idx=pad_idx,
                start_idx=start_idx,
                end_idx=end_idx,
                link=link,
                device=device,
            )
        )

    original_text = ids_to_text(source_ids, idx_to_token, args.show_special_tokens)
    if args.requirement_type == "low-latency":
        gate_text = f"low-latency, delay<={args.delay_threshold:g}s"
    else:
        gate_text = f"high-fidelity, TokenMatch>={args.sim_threshold:g}"

    print("\n=== Legacy Semantic Communication Demo ===")
    print(f"DeepSC root      : {deepsc_root}")
    print(f"Submitted task   : {task.task_id} ({TASK_ASSETS[task.profile]['label']})")
    print(f"Task data        : {task.assets['data']} [sample {task.sample_index}]")
    print(f"Task vocab       : {task.assets['vocab']}")
    print(f"Knowledge match  : {sem_nssai:.2f}%")
    print(f"Channel          : AWGN, SNR computed from per-slice P/B resources")
    print(
        f"Resource caps    : P_total={args.total_power:g}, "
        f"B_total={args.total_bandwidth:g} MHz"
    )
    print(
        "Slice resources  : "
        + ", ".join(
            f"slice-{idx + 1} P={slice_power[idx]:.4g}, B={slice_bandwidth[idx]:.4g}MHz"
            for idx in range(len(SLICE_CONFIG))
        )
    )
    print(
        f"Link constants   : d={args.distance_m:g}m, N0={args.noise_dbm:g}dBm, "
        f"K={args.semantic_symbols}, L={args.symbol_length}"
    )
    print(f"Task gate        : {gate_text}")
    print(f"Seed             : {args.seed}")
    print(f"Device           : {device}")

    print("\n--- Tensor Path (same shape path for each strategy) ---")
    for name, shape in results[0].shapes.items():
        print(f"{name:24s}: {shape}")

    print("\n--- Input Sentence ---")
    print(f"Original         : {original_text}")

    print("\n--- Strategy Comparison ---")
    print(
        f"{'Strategy':10s} {'Rule':28s} {'Slice':7s} {'P':>7s} {'B(MHz)':>8s} "
        f"{'SNR(dB)':>8s} {'Delay(ms)':>10s} {'TokenMatch':>10s} {'Pass':>5s} "
        f"{'S-SE':>7s} Checkpoint"
    )
    print("-" * 132)
    for result in results:
        print(
            f"{result.strategy:10s} {result.description:28s} "
            f"{result.slice_idx + 1:<7d} "
            f"{result.link.power:7.4f} {result.link.bandwidth_mhz:8.4f} "
            f"{result.link.snr_db:8.2f} {result.link.delay_ms:10.4f} "
            f"{result.token_match_rate:10.2%} {str(result.task_passed):>5s} "
            f"{result.s_se:7.4f} {result.checkpoint_name}"
        )

    print("\n--- Link Details ---")
    for result in results:
        print(
            f"{result.strategy:10s}: capacity={result.link.capacity_mbps:.4f} Mbps, "
            f"noise_std={result.link.noise_std:.6f}, "
            f"len={result.source_len}->{result.decoded_len}"
        )

    print("\n--- Decoded Sentences ---")
    for result in results:
        print(f"{result.strategy:10s}: {result.decoded_text}")

    print(
        "\nNo BERT model or semantic-similarity score is used. "
        "TokenMatch is only a lightweight word-id position match for demo comparison."
    )


if __name__ == "__main__":
    main()
