import math
import random
from typing import Dict, List, Tuple

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


def evaluate_legacy_vector(strategy: str, scenario: str, resource_vector: List[float]) -> Tuple[float, List[float], object]:
    normalized = "random" if str(strategy).strip().lower() in {"noslice", "no_slice", "random"} else strategy
    return _simulate_legacy_details(scenario, normalized, resource_vector)


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
