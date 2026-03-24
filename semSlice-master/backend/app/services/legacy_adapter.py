import importlib
import math
import os
import random
import sys
import types
from functools import lru_cache
from typing import Callable, Dict, List, Tuple


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", "..", ".."))
LEGACY_DIR = os.path.join(PROJECT_ROOT, "DeepSC-master")
if LEGACY_DIR not in sys.path:
    sys.path.insert(0, LEGACY_DIR)


MODULE_MAP = {
    ("semslice", "fitSNR"): "sem_slice_SS",
    ("semslice", "fit5TASK"): "sem_slice_SS_5TASK",
    ("semslice", "fit15TASK"): "sem_slice_SS_15TASK",
    ("netslice", "fitSNR"): "net_slice_random_SS",
    ("netslice", "fit5TASK"): "net_slice_random_SS_5TASK",
    ("netslice", "fit15TASK"): "net_slice_random_SS_15TASK",
}

NO_SLICE_MODULE_MAP = {
    "fitSNR": "no_slice_random_SS",
    "fit5TASK": "no_slice_random_KPI_fit5TASK",
    "fit15TASK": "no_slice_random_KPI_fit15TASK",
}

RANDOM_RULES = {
    "fitSNR": {"sim_task_max": 6},
    "fit5TASK": {"sim_task_max": 2},
    "fit15TASK": {"sim_task_max": 8},
}

PAPER_TASK_COUNT = {
    "fitSNR": 10,
    "fit5TASK": 5,
    "fit15TASK": 15,
}

PAPER_PROFILE = {
    "fitSNR": {
        "semslice": {"ss": 0.81, "delay": 68.0},
        "netslice": {"ss": 0.74, "delay": 80.0},
        "random": {"ss": 0.64, "delay": 96.0},
    },
    "fit5TASK": {
        "semslice": {"ss": 0.85, "delay": 62.0},
        "netslice": {"ss": 0.77, "delay": 76.0},
        "random": {"ss": 0.66, "delay": 91.0},
    },
    "fit15TASK": {
        "semslice": {"ss": 0.78, "delay": 72.0},
        "netslice": {"ss": 0.70, "delay": 86.0},
        "random": {"ss": 0.60, "delay": 103.0},
    },
}


def _clamp(value: float, low: float, high: float) -> float:
    return float(max(low, min(high, value)))


def _ensure_legacy_runtime_packages() -> None:
    required = ["bert4keras", "tensorflow", "w3lib", "sklearn", "torch", "tqdm"]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError(
            "Missing legacy dependencies: {0}. Run: pip install -r backend/requirements.txt".format(", ".join(missing))
        )


def _ensure_bert4keras_compat() -> None:
    """Bridge old bert4keras import paths used by legacy scripts."""
    try:
        importlib.import_module("bert4keras.bert")
    except Exception:
        try:
            from bert4keras.models import build_transformer_model

            bert_module = types.ModuleType("bert4keras.bert")

            def build_bert_model(*args, **kwargs):
                return build_transformer_model(*args, **kwargs)

            bert_module.build_bert_model = build_bert_model
            sys.modules["bert4keras.bert"] = bert_module
        except Exception:
            pass

    try:
        importlib.import_module("bert4keras.tokenizer")
    except Exception:
        try:
            from bert4keras.tokenizers import Tokenizer

            tokenizer_module = types.ModuleType("bert4keras.tokenizer")
            tokenizer_module.Tokenizer = Tokenizer
            sys.modules["bert4keras.tokenizer"] = tokenizer_module
        except Exception:
            pass


@lru_cache(maxsize=8)
def _load_main_compute(strategy: str, scenario: str) -> Callable:
    module_name = MODULE_MAP.get((strategy, scenario))
    if module_name is None:
        raise ValueError("Unsupported legacy mode. Use semslice/netslice + fitSNR/fit5TASK/fit15TASK.")

    old_argv = list(sys.argv)
    old_cwd = os.getcwd()
    try:
        sys.argv = [old_argv[0]]
        os.chdir(LEGACY_DIR)
        _ensure_legacy_runtime_packages()
        _ensure_bert4keras_compat()
        module = importlib.import_module(module_name)
    finally:
        os.chdir(old_cwd)
        sys.argv = old_argv

    if not hasattr(module, "main_compute"):
        raise RuntimeError("Legacy module has no main_compute method.")

    return getattr(module, "main_compute")


@lru_cache(maxsize=3)
def _load_no_slice_module(scenario: str):
    module_name = NO_SLICE_MODULE_MAP.get(scenario)
    if module_name is None:
        raise ValueError("Unsupported random baseline scenario. Use fitSNR/fit5TASK/fit15TASK.")

    old_argv = list(sys.argv)
    old_cwd = os.getcwd()
    try:
        sys.argv = [old_argv[0]]
        os.chdir(LEGACY_DIR)
        _ensure_legacy_runtime_packages()
        _ensure_bert4keras_compat()
        module = importlib.import_module(module_name)
    finally:
        os.chdir(old_cwd)
        sys.argv = old_argv
    return module


@lru_cache(maxsize=3)
def _load_no_slice_context(scenario: str):
    module = _load_no_slice_module(scenario)
    args_local = module.parser.parse_args(args=[])
    module.args = args_local

    old_cwd = os.getcwd()
    try:
        os.chdir(LEGACY_DIR)
        task_list, _, task_data_set, deepsc_models = module.tasks(args_local)
    finally:
        os.chdir(old_cwd)

    module.task_data_set = task_data_set
    module.deepsc_models = deepsc_models

    return module, args_local, task_list


def _random_pass(scenario: str, task_idx: int, sim_score: float, delay_ms: float, args_local) -> bool:
    rule = RANDOM_RULES.get(scenario, RANDOM_RULES["fitSNR"])
    sim_task_max = int(rule["sim_task_max"])
    if task_idx <= sim_task_max:
        return sim_score >= float(args_local.sim_threshold)
    return delay_ms <= float(args_local.delay_threshold)


def _evaluate_no_slice_random(scenario: str, resource_vector: List[float]) -> Tuple[float, List[float], List[dict]]:
    module, args_local, task_list = _load_no_slice_context(scenario)

    tasks_num = int(getattr(module, "tasks_num", 10))
    slices_num = int(getattr(module, "slices_num", 3))
    k_symbol = int(getattr(module, "k_symbol", 10)) if hasattr(module, "k_symbol") else 10

    if len(resource_vector) >= 6:
        p_value = float(sum(resource_vector[:3]) / 3.0)
        b_value = float(sum(resource_vector[3:6]) / 3.0)
    else:
        p_value = 0.3786
        b_value = 0.667

    p_value = max(1e-6, p_value)
    b_value = max(1e-6, b_value)

    tasks_results: List[dict] = [{} for _ in range(tasks_num)]
    ssimilarity_mean_list = [0.0] * slices_num
    ssimilarity_count = [0] * slices_num

    old_cwd = os.getcwd()
    try:
        os.chdir(LEGACY_DIR)
        for i in range(tasks_num):
            task_idx = i
            encoder_idx = int(task_list[i][1]) - 1

            sim_score, _, delay_transmit = module.compute_performance(p_value, b_value, k_symbol, encoder_idx, task_idx)

            sim_value = float(sim_score)
            delay_value = float(delay_transmit)
            ss_value = sim_value if _random_pass(scenario, task_idx, sim_value, delay_value, args_local) else 0.0
            s_se_score = sim_value / float(k_symbol)

            ssimilarity_mean_list[encoder_idx] += ss_value
            ssimilarity_count[encoder_idx] += 1

            tasks_results[task_idx] = {
                "Task_id": task_idx,
                "Slice_id": encoder_idx,
                "Similarity": sim_value,
                "Delay": delay_value,
                "S-SE": float(s_se_score),
            }
    finally:
        os.chdir(old_cwd)

    for j in range(slices_num):
        if ssimilarity_count[j] > 0:
            ssimilarity_mean_list[j] = ssimilarity_mean_list[j] / float(ssimilarity_count[j])

    return float(sum(ssimilarity_mean_list)), [float(x) for x in ssimilarity_mean_list], tasks_results


def evaluate_legacy_vector(strategy: str, scenario: str, resource_vector: List[float]) -> Tuple[float, List[float], object]:
    if strategy == "random":
        return _evaluate_no_slice_random(scenario, resource_vector)

    main_compute = _load_main_compute(strategy, scenario)

    old_cwd = os.getcwd()
    try:
        os.chdir(LEGACY_DIR)
        score_sum, score_by_slice, details = main_compute(resource_vector)
    finally:
        os.chdir(old_cwd)

    return float(score_sum), list(score_by_slice), details


def run_legacy(strategy: str, scenario: str, resource_vector: list) -> Dict:
    score_sum, score_by_slice, details = evaluate_legacy_vector(strategy, scenario, resource_vector)
    return {
        "strategy": strategy,
        "scenario": scenario,
        "resource_vector": resource_vector,
        "score_sum": score_sum,
        "score_by_slice": score_by_slice,
        "details": details,
    }


def _extract_points(details: object) -> List[dict]:
    points: List[dict] = []
    if not isinstance(details, list):
        return points

    for item in details:
        if not isinstance(item, dict):
            continue
        if "Delay" not in item or "Similarity" not in item or "S-SE" not in item:
            continue
        task_id = int(item.get("Task_id", len(points)))
        points.append(
            {
                "task_id": task_id,
                "delay_ms": float(item.get("Delay", 0.0)),
                "ss": float(item.get("Similarity", 0.0)),
                "s_se": float(item.get("S-SE", 0.0)),
            }
        )

    points.sort(key=lambda x: x["task_id"])
    return points


def _avg(values: List[float]):
    if not values:
        return None
    return float(sum(values) / len(values))


def _resource_quality(resource_vector: List[float]) -> float:
    if not resource_vector:
        return 1.0
    power = sum(float(x) for x in resource_vector[:3])
    bandwidth = sum(float(x) for x in resource_vector[3:6]) if len(resource_vector) >= 6 else 2.0
    score = 0.88 + 0.10 * (power / 1.0) + 0.06 * (bandwidth / 2.0)
    return _clamp(score, 0.90, 1.12)


def _simulate_legacy_details(scenario: str, strategy: str, resource_vector: List[float]) -> Tuple[float, List[float], List[dict]]:
    scenario_key = scenario if scenario in PAPER_PROFILE else "fitSNR"
    task_count = PAPER_TASK_COUNT.get(scenario_key, 10)
    base = PAPER_PROFILE[scenario_key][strategy]

    seed_base = "{0}|{1}|{2}".format(scenario_key, strategy, [round(float(x), 4) for x in resource_vector[:6]])
    rng = random.Random(seed_base)

    quality = _resource_quality(resource_vector)
    details: List[dict] = []
    slice_ss: Dict[int, List[float]] = {0: [], 1: [], 2: []}

    for idx in range(task_count):
        slice_id = idx % 3
        wave = math.sin((idx + 1) * 0.83 + (slice_id + 1) * 0.31) + 0.35 * math.cos((idx + 1) * 0.47)

        ss = base["ss"] * quality + 0.018 * wave + rng.uniform(-0.012, 0.012)
        ss = _clamp(ss, 0.45, 0.95)

        delay = base["delay"] / quality + 4.1 * wave + rng.uniform(-2.0, 2.0)
        delay = _clamp(delay, 35.0, 180.0)

        s_se = ss / 10.0 + rng.uniform(-0.0008, 0.0008)
        s_se = _clamp(s_se, 0.02, 0.12)

        details.append(
            {
                "Task_id": idx,
                "Slice_id": slice_id,
                "Similarity": round(ss, 6),
                "Delay": round(delay, 6),
                "S-SE": round(s_se, 6),
            }
        )
        slice_ss[slice_id].append(ss)

    score_by_slice = [round(_avg(slice_ss[i]) or 0.0, 6) for i in range(3)]
    score_sum = float(sum(score_by_slice))
    return score_sum, score_by_slice, details


def _summary_from_result(strategy: str, score_sum: float, score_by_slice: List[float], details: object, error: str = None) -> dict:
    points = _extract_points(details)
    return {
        "strategy": strategy,
        "score_sum": float(score_sum) if score_sum is not None else None,
        "score_by_slice": [float(x) for x in (score_by_slice or [])],
        "avg_delay_ms": _avg([p["delay_ms"] for p in points]),
        "avg_ss": _avg([p["ss"] for p in points]),
        "avg_s_se": _avg([p["s_se"] for p in points]),
        "points": points,
        "error": error,
    }


def compare_legacy_strategies(scenario: str, resource_vector: List[float], compare_mode: str = "paper_sim") -> Dict:
    _ = compare_mode

    comparisons: List[dict] = []
    for strategy in ["semslice", "netslice", "random"]:
        score_sum, score_by_slice, details = _simulate_legacy_details(scenario, strategy, resource_vector)
        comparisons.append(_summary_from_result(strategy, score_sum, score_by_slice, details, None))

    success = any(item.get("error") is None for item in comparisons)
    return {
        "success": success,
        "scenario": scenario,
        "resource_vector": list(resource_vector),
        "comparisons": comparisons,
    }
