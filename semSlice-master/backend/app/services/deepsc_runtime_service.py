import json
import math
import pickle
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from app.models.schemas import NetworkConfig, SliceInstance, UserBusinessItem, UserResourceAllocation
from app.services.semantic_service import OLD_DISTANCE_M, OLD_NOISE_DBM, compute_snr_db, transmit_delay_ms


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEEPSC_ROOT = PROJECT_ROOT / "DeepSC-master"

SPECIAL_TOKENS = {"<PAD>", "<START>", "<END>", "<UNK>"}
FULL_PROFILE = "full"
PROFILE_ORDER = ("full", "en90", "en80")
PROFILE_ASSETS = {
    "full": {
        "vocab": "vocab_en.json",
        "data": "test_data_en.pkl",
        "model_dir": "deepsc-AWGN-enorigin_layer3",
        "label": "enorigin",
    },
    "en90": {
        "vocab": "vocab_en90%.json",
        "data": "test_data-en90%.pkl",
        "model_dir": "deepsc-AWGN-en90%_layer3",
        "label": "en90",
    },
    "en80": {
        "vocab": "vocab_en80%.json",
        "data": "test_data-en80%.pkl",
        "model_dir": "deepsc-AWGN-en80%_layer3",
        "label": "en80",
    },
}
PKL_TO_VOCAB = {
    "test_data_en.pkl": "vocab_en.json",
    "test_data-en90%.pkl": "vocab_en90%.json",
    "test_data-en80%.pkl": "vocab_en80%.json",
}
VOCAB_TO_PROFILE = {assets["vocab"]: profile for profile, assets in PROFILE_ASSETS.items()}
PKL_TO_PROFILE = {assets["data"]: profile for profile, assets in PROFILE_ASSETS.items()}

MAX_LENGTH = 20
NUM_LAYERS = 3
D_MODEL = 128
DFF = 512
NUM_HEADS = 8
SYMBOL_LENGTH = 30

_VOCAB_CACHE: Dict[str, Dict[str, int]] = {}
_DATA_CACHE: Dict[str, List[List[int]]] = {}
_MODEL_CACHE: Dict[Tuple[str, str], object] = {}
_CHECKPOINT_CACHE: Dict[str, Path] = {}


def _safe_name(value: Optional[str], fallback: str) -> str:
    name = Path(str(value or fallback)).name
    return name or fallback


def _norm(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def infer_profile_from_name(value: Optional[str]) -> str:
    token = _norm(str(value or ""))
    if "90" in token:
        return "en90"
    if "80" in token:
        return "en80"
    return "full"


def profile_for_slice_id(slice_id: str) -> str:
    token = _norm(slice_id)
    if token.endswith("2") or "90" in token:
        return "en90"
    if token.endswith("3") or "80" in token:
        return "en80"
    return "full"


def profile_for_slice(slice_item: SliceInstance) -> str:
    probe = " ".join([slice_item.slice_id, slice_item.slice_name, slice_item.kb_id, slice_item.kb_type])
    if "slice2" in _norm(slice_item.slice_id):
        return "en90"
    if "slice3" in _norm(slice_item.slice_id):
        return "en80"
    return infer_profile_from_name(probe)


def slice_index_for_profile(profile: str) -> int:
    return PROFILE_ORDER.index(profile)


def _asset_path(name: str) -> Path:
    return DEEPSC_ROOT / Path(name).name


def resolve_task_files(user: UserBusinessItem) -> Tuple[str, str, str]:
    pkl_name = _safe_name(user.task_pkl, PROFILE_ASSETS["full"]["data"])
    vocab_name = _safe_name(user.task_vocab, PKL_TO_VOCAB.get(pkl_name, PROFILE_ASSETS["full"]["vocab"]))

    if pkl_name not in PKL_TO_PROFILE:
        profile = infer_profile_from_name(pkl_name)
        pkl_name = PROFILE_ASSETS[profile]["data"]
    if vocab_name not in VOCAB_TO_PROFILE:
        profile = infer_profile_from_name(vocab_name)
        vocab_name = PROFILE_ASSETS[profile]["vocab"]

    task_profile = VOCAB_TO_PROFILE.get(vocab_name) or PKL_TO_PROFILE.get(pkl_name) or "full"
    return task_profile, pkl_name, vocab_name


def _normalize_strategy_name(raw: Optional[str]) -> str:
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


def resolve_decode_files(user: UserBusinessItem, strategy: Optional[str]) -> Tuple[str, str, str]:
    task_profile, pkl_name, vocab_name = resolve_task_files(user)
    normalized = _normalize_strategy_name(strategy)
    if normalized in {"netslice", "noslice"}:
        task_profile = PKL_TO_PROFILE.get(pkl_name, "full")
        vocab_name = PROFILE_ASSETS["full"]["vocab"]
    return task_profile, pkl_name, vocab_name


def load_vocab_by_name(vocab_name: str) -> Dict[str, int]:
    safe = _safe_name(vocab_name, PROFILE_ASSETS["full"]["vocab"])
    if safe in _VOCAB_CACHE:
        return _VOCAB_CACHE[safe]
    path = _asset_path(safe)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    vocab = payload["token_to_idx"]
    _VOCAB_CACHE[safe] = vocab
    return vocab


def load_data_by_name(pkl_name: str) -> List[List[int]]:
    safe = _safe_name(pkl_name, PROFILE_ASSETS["full"]["data"])
    if safe in _DATA_CACHE:
        return _DATA_CACHE[safe]
    path = _asset_path(safe)
    with path.open("rb") as handle:
        data = pickle.load(handle)
    _DATA_CACHE[safe] = data
    return data


def knowledge_match_percent_for_vocab(vocab_name: str) -> float:
    full_vocab = load_vocab_by_name(PROFILE_ASSETS["full"]["vocab"])
    task_vocab = load_vocab_by_name(vocab_name)
    full_keys = set(full_vocab.keys())
    task_keys = set(task_vocab.keys())
    return 100.0 * len(full_keys & task_keys) / max(len(full_keys), 1)


def select_profile_by_match(match_percent: float) -> str:
    if match_percent >= 95:
        return "full"
    if 85 <= match_percent < 95:
        return "en90"
    if 75 <= match_percent < 85:
        return "en80"
    return "en80"


def select_slice_for_profile(profile: str, slices: List[SliceInstance]) -> SliceInstance:
    for slice_item in slices:
        if profile_for_slice(slice_item) == profile:
            return slice_item
    index = min(slice_index_for_profile(profile), len(slices) - 1)
    return slices[index]


def semantic_slice_for_user(user: UserBusinessItem, slices: List[SliceInstance]) -> Tuple[SliceInstance, float]:
    _, _, vocab_name = resolve_task_files(user)
    match_percent = knowledge_match_percent_for_vocab(vocab_name)
    profile = select_profile_by_match(match_percent)
    return select_slice_for_profile(profile, slices), match_percent / 100.0


def _latest_checkpoint(profile: str) -> Path:
    if profile in _CHECKPOINT_CACHE:
        return _CHECKPOINT_CACHE[profile]
    model_dir = DEEPSC_ROOT / PROFILE_ASSETS[profile]["model_dir"]
    checkpoints: List[Tuple[int, Path]] = []
    for path in model_dir.glob("*.pth"):
        match = re.search(r"_(\d+)\.pth$", path.name)
        if match:
            checkpoints.append((int(match.group(1)), path))
    if not checkpoints:
        raise FileNotFoundError("No checkpoint_XX.pth files found in {0}".format(model_dir))
    checkpoints.sort(key=lambda item: item[0])
    _CHECKPOINT_CACHE[profile] = checkpoints[-1][1]
    return checkpoints[-1][1]


def _load_runtime():
    import numpy as np
    import torch

    if str(DEEPSC_ROOT) not in sys.path:
        sys.path.insert(0, str(DEEPSC_ROOT))
    from models.transceiver import DeepSC

    return np, torch, DeepSC


def _load_model(profile: str, vocab_size: int, device):
    _, torch, DeepSC = _load_runtime()
    key = (profile, str(device))
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    checkpoint_path = _latest_checkpoint(profile)
    model = DeepSC(
        NUM_LAYERS,
        vocab_size,
        vocab_size,
        vocab_size,
        vocab_size,
        D_MODEL,
        NUM_HEADS,
        DFF,
        0.1,
    ).to(device)
    state = torch.load(checkpoint_path, map_location=device)
    model.load_state_dict(state)
    model.eval()
    _MODEL_CACHE[key] = model
    return model


def snr_to_noise_std(snr_db: float) -> float:
    snr_linear = 10 ** (snr_db / 10)
    return float(1 / math.sqrt(2 * snr_linear))


def link_metrics_for_user(
    user: UserBusinessItem,
    allocation: UserResourceAllocation,
    network: NetworkConfig,
) -> Dict[str, float]:
    snr_db = compute_snr_db(
        power=max(1e-6, float(allocation.power)),
        bandwidth_mhz=max(1e-6, float(allocation.bandwidth)),
        distance_m=OLD_DISTANCE_M,
        noise_dbm=OLD_NOISE_DBM,
    )
    delay_ms = transmit_delay_ms(
        int(user.payload_symbols),
        SYMBOL_LENGTH,
        max(1e-6, float(allocation.bandwidth)),
        snr_db,
    )
    snr_linear = 10 ** (snr_db / 10)
    capacity_bps = max(1e-9, float(allocation.bandwidth) * 1e6 * math.log2(1 + snr_linear))
    return {
        "snr_db": round(snr_db, 4),
        "delay_ms": round(delay_ms, 4),
        "noise_std": snr_to_noise_std(snr_db),
        "capacity_mbps": capacity_bps / 1e6,
        "noise_dbm": OLD_NOISE_DBM,
    }


def _power_normalize(x, torch):
    power = torch.mean(torch.mul(x, x)).sqrt()
    if power > 1:
        return torch.div(x, power)
    return x


def _signal_preview(tensor, field_prefix: str = "encoded_signal", limit: int = 24) -> Dict[str, str]:
    flat = tensor.detach().cpu().reshape(-1).tolist()
    values = ", ".join("{0:.4f}".format(float(value)) for value in flat[:limit])
    if len(flat) > limit:
        values = "{0}, ...".format(values)
    return {
        "{0}_shape".format(field_prefix): "x".join(str(int(dim)) for dim in tensor.shape),
        "{0}_preview".format(field_prefix): "[{0}]".format(values),
    }


def _subsequent_mask(size: int, device, np, torch):
    mask = np.triu(np.ones((1, size, size)), k=1).astype("uint8")
    return torch.from_numpy(mask).type(torch.float32).to(device)


def _semantic_roundtrip(model, src, noise_std: float, pad_idx: int, start_idx: int, np, torch) -> Dict[str, object]:
    device = src.device
    with torch.no_grad():
        src_mask = (src == pad_idx).unsqueeze(-2).type(torch.float32).to(device)
        enc_output = model.encoder(src, src_mask)
        channel_enc_output = model.channel_encoder(enc_output)
        tx_sig = _power_normalize(channel_enc_output, torch)
        encoded_snapshot = _signal_preview(tx_sig)
        rx_sig = tx_sig + torch.normal(mean=0.0, std=noise_std, size=tx_sig.shape, device=device)
        try:
            memory = model.channel_decoder(rx_sig)

            outputs = torch.ones(src.size(0), 1, dtype=src.dtype, device=device).fill_(start_idx)
            for _ in range(MAX_LENGTH - 1):
                trg_mask = (outputs == pad_idx).unsqueeze(-2).type(torch.float32)
                look_ahead_mask = _subsequent_mask(outputs.size(1), device, np, torch)
                combined_mask = torch.max(trg_mask.to(device), look_ahead_mask)
                dec_output = model.decoder(outputs, memory, combined_mask, None)
                pred = model.dense(dec_output)
                next_word = torch.max(pred[:, -1:, :], dim=-1)[1]
                outputs = torch.cat([outputs, next_word], dim=1)
            return {
                "decoded_ids": outputs[0].detach().cpu().tolist(),
                "decode_error": "",
                **encoded_snapshot,
            }
        except Exception as exc:
            return {
                "decoded_ids": [],
                "decode_error": str(exc),
                **encoded_snapshot,
            }


def ids_to_text(ids: Iterable[int], idx_to_token: Dict[int, str]) -> str:
    words: List[str] = []
    for raw_idx in ids:
        token = idx_to_token.get(int(raw_idx), "<UNK>")
        if token == "<END>":
            break
        if token not in SPECIAL_TOKENS:
            words.append(token)
    return " ".join(words)


def _strip_special_ids(ids: Iterable[int], pad_idx: int, start_idx: int, end_idx: int) -> List[int]:
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
    matches = sum(1 for left, right in zip(source_ids, decoded_ids) if int(left) == int(right))
    return matches / denom


def service_passed(requirement_type: str, fidelity: float, delay_ms: float) -> bool:
    value = str(requirement_type or "").strip().lower().replace("-", "_")
    if value == "low_latency":
        return float(delay_ms) <= 130.0
    return float(fidelity) >= 0.60


def real_decode_for_user(
    user: UserBusinessItem,
    allocation: UserResourceAllocation,
    network: NetworkConfig,
    strategy: Optional[str] = "semslice",
) -> Dict[str, object]:
    task_profile, pkl_name, vocab_name = resolve_decode_files(user, strategy)
    model_profile = profile_for_slice_id(allocation.slice_id)
    sample_index = int(getattr(user, "sample_index", 0))
    encoded_snapshot = {"encoded_signal_shape": "", "encoded_signal_preview": ""}
    link = {"snr_db": 0.0, "delay_ms": 0.0, "noise_std": 0.0, "capacity_mbps": 0.0, "noise_dbm": OLD_NOISE_DBM}
    source_text = ""
    source_clean: List[int] = []
    checkpoint_name = ""

    try:
        link = link_metrics_for_user(user, allocation, network)
        full_vocab = load_vocab_by_name(PROFILE_ASSETS["full"]["vocab"])
        idx_to_token = {idx: token for token, idx in full_vocab.items()}
        pad_idx = full_vocab["<PAD>"]
        start_idx = full_vocab["<START>"]
        end_idx = full_vocab["<END>"]
        task_data = load_data_by_name(pkl_name)
        if not 0 <= sample_index < len(task_data):
            raise IndexError("sample_index {0} is outside 0..{1}".format(sample_index, len(task_data) - 1))

        source_ids = [int(item) for item in task_data[sample_index]]
        source_clean = _strip_special_ids(source_ids, pad_idx, start_idx, end_idx)
        source_text = ids_to_text(source_ids, idx_to_token)
        np, torch, _ = _load_runtime()
        device = torch.device("cpu")
        checkpoint_name = _latest_checkpoint(model_profile).name
        model = _load_model(model_profile, len(full_vocab), device)
        src = torch.tensor([source_ids], dtype=torch.long, device=device)
        roundtrip = _semantic_roundtrip(model, src, float(link["noise_std"]), pad_idx, start_idx, np, torch)
        encoded_snapshot = {
            "encoded_signal_shape": str(roundtrip.get("encoded_signal_shape", "")),
            "encoded_signal_preview": str(roundtrip.get("encoded_signal_preview", "")),
        }
        decode_error = str(roundtrip.get("decode_error", ""))
        if decode_error:
            return {
                "decode_ok": False,
                "source_text": source_text,
                "decoded_text": "",
                "token_match_rate": 0.0,
                "pass": False,
                "source_len": len(source_clean),
                "decoded_len": 0,
                "task_profile": task_profile,
                "model_profile": model_profile,
                "task_pkl": pkl_name,
                "task_vocab": vocab_name,
                "sample_index": sample_index,
                "checkpoint_name": checkpoint_name,
                "decode_error": decode_error,
                **encoded_snapshot,
                **link,
            }
        decoded_ids = [int(item) for item in roundtrip.get("decoded_ids", [])]
        decoded_clean = _strip_special_ids(decoded_ids, pad_idx, start_idx, end_idx)
        score = token_match_rate(source_clean, decoded_clean)
        decoded_text = ids_to_text(decoded_ids, idx_to_token)
        passed = service_passed(user.requirement_type, score, float(link["delay_ms"]))
        return {
            "decode_ok": True,
            "source_text": source_text,
            "decoded_text": decoded_text,
            "token_match_rate": round(score, 4),
            "pass": passed,
            "source_len": len(source_clean),
            "decoded_len": len(decoded_clean),
            "task_profile": task_profile,
            "model_profile": model_profile,
            "task_pkl": pkl_name,
            "task_vocab": vocab_name,
            "sample_index": sample_index,
            "checkpoint_name": checkpoint_name,
            "decode_error": "",
            **encoded_snapshot,
            **link,
        }
    except Exception as exc:
        return {
            "decode_ok": False,
            "source_text": source_text,
            "decoded_text": "",
            "token_match_rate": 0.0,
            "pass": False,
            "source_len": len(source_clean),
            "decoded_len": 0,
            "task_profile": task_profile,
            "model_profile": model_profile,
            "task_pkl": pkl_name,
            "task_vocab": vocab_name,
            "sample_index": sample_index,
            "checkpoint_name": checkpoint_name,
            "decode_error": str(exc),
            **encoded_snapshot,
            **link,
        }
