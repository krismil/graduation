import random
from typing import Dict, List

from app.models.schemas import AdaptationRequest, AdaptationResponse, AdaptationRow, SliceInstance, UserBusinessItem
from app.services.deepsc_runtime_service import (
    profile_for_slice,
    resolve_task_files,
    semantic_slice_for_user,
)


RANDOM_SEED = 2026
_VOCAB_LEVEL = {"en": 1.0, "en90": 0.9, "en80": 0.8}


def _norm(text: str) -> str:
    return str(text or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _infer_vocab_tag_from_text(text: str) -> str:
    token = _norm(text)
    if "90" in token:
        return "en90"
    if "80" in token:
        return "en80"
    if "en" in token:
        return "en"
    return "en"


def _user_vocab_tag(user: UserBusinessItem) -> str:
    try:
        profile, _, _ = resolve_task_files(user)
        return "en" if profile == "full" else profile
    except Exception:
        for value in [user.task_vocab, user.task_pkl, user.domain_type]:
            if value:
                return _infer_vocab_tag_from_text(value)
        return "en"


def _slice_vocab_tag(slice_item: SliceInstance) -> str:
    try:
        profile = profile_for_slice(slice_item)
        return "en" if profile == "full" else profile
    except Exception:
        probe = " ".join([slice_item.kb_type, slice_item.kb_id, slice_item.slice_name])
        return _infer_vocab_tag_from_text(probe)


def _similarity(user: UserBusinessItem, slice_item: SliceInstance) -> float:
    user_tag = _user_vocab_tag(user)
    slice_tag = _slice_vocab_tag(slice_item)
    user_level = _VOCAB_LEVEL.get(user_tag, 1.0)
    slice_level = _VOCAB_LEVEL.get(slice_tag, 1.0)
    gap = abs(user_level - slice_level)

    if gap < 1e-6:
        score = 0.97
    elif gap <= 0.1:
        score = 0.85
    else:
        score = 0.75

    if user.requirement_type == "high_fidelity":
        score += 0.02
    elif user.requirement_type == "low_latency":
        score += 0.01
    return max(0.0, min(1.0, score))


def _choose_slice_by_vocab(user: UserBusinessItem, slices: List[SliceInstance]) -> SliceInstance:
    try:
        selected, _ = semantic_slice_for_user(user, slices)
        return selected
    except Exception:
        pass
    scored = sorted(
        ((slice_item, _similarity(user, slice_item)) for slice_item in slices),
        key=lambda item: (item[1], item[0].knowledge_level),
        reverse=True,
    )
    return scored[0][0]


def _stable_seed(method: str, users: List[UserBusinessItem], slices: List[SliceInstance]) -> int:
    seed_text = "|".join(
        [method]
        + [str(user.user_id) for user in users]
        + [str(slice_item.slice_id) for slice_item in slices]
    )
    return RANDOM_SEED + sum((idx + 1) * ord(char) for idx, char in enumerate(seed_text))


def _random_slice_map(
    users: List[UserBusinessItem],
    slices: List[SliceInstance],
    method: str,
) -> Dict[str, SliceInstance]:
    if not users or not slices:
        return {}

    rng = random.Random(_stable_seed(method, users, slices))
    if len(users) >= len(slices):
        chosen = list(slices)
        while len(chosen) < len(users):
            chosen.append(slices[rng.randrange(len(slices))])
        rng.shuffle(chosen)
    else:
        chosen = rng.sample(slices, len(users))

    return {user.user_id: chosen[idx] for idx, user in enumerate(users)}


def adapt_users_to_slices(payload: AdaptationRequest) -> AdaptationResponse:
    if not payload.slices:
        return AdaptationResponse(relations=[])

    method = _norm(payload.method)
    if method in {"random", "no_slice"}:
        method = "noslice"
    random_map = _random_slice_map(payload.users, payload.slices, method) if method in {"netslice", "noslice"} else {}

    relations = []
    for user in payload.users:
        if method in {"netslice", "noslice"}:
            best_slice = random_map.get(user.user_id, payload.slices[0])
            score = 0.0
        else:
            try:
                best_slice, score = semantic_slice_for_user(user, payload.slices)
            except Exception:
                best_slice = _choose_slice_by_vocab(user, payload.slices)
                score = _similarity(user, best_slice)

        relations.append(
            AdaptationRow(
                user_id=user.user_id,
                domain_type=user.domain_type,
                requirement_type=user.requirement_type,
                matched_slice_id=best_slice.slice_id,
                matched_slice_name=best_slice.slice_name,
                codec_id=best_slice.codec_id,
                kb_id=best_slice.kb_id,
                similarity_score=round(score, 4),
            )
        )

    return AdaptationResponse(relations=relations)
