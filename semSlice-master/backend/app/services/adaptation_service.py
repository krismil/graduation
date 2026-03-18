from typing import List

from app.models.schemas import AdaptationRequest, AdaptationResponse, AdaptationRow, SliceInstance, UserBusinessItem


def _similarity(user: UserBusinessItem, slice_item: SliceInstance) -> float:
    domain_match = 1.0 if user.domain_type == slice_item.kb_type else 0.45
    requirement_bonus = 0.10 if user.requirement_type == "high_fidelity" else 0.05
    latency_bonus = 0.10 if user.requirement_type == "low_latency" and slice_item.knowledge_level >= 0.85 else 0.0
    score = 0.55 * domain_match + 0.35 * slice_item.knowledge_level + requirement_bonus + latency_bonus
    return max(0.0, min(1.0, score))


def _choose_slice_by_domain(user: UserBusinessItem, slices: List[SliceInstance]) -> SliceInstance:
    for slice_item in slices:
        if slice_item.kb_type == user.domain_type:
            return slice_item
    return sorted(slices, key=lambda item: item.knowledge_level, reverse=True)[0]


def adapt_users_to_slices(payload: AdaptationRequest) -> AdaptationResponse:
    if not payload.slices:
        return AdaptationResponse(relations=[])

    relations = []
    for user in payload.users:
        if payload.method == "domain":
            best_slice = _choose_slice_by_domain(user, payload.slices)
            score = _similarity(user, best_slice)
        else:
            scored = sorted(
                ((slice_item, _similarity(user, slice_item)) for slice_item in payload.slices),
                key=lambda item: item[1],
                reverse=True,
            )
            best_slice, score = scored[0]

        relations.append(
            AdaptationRow(
                user_id=user.user_id,
                tenant_id=user.tenant_id,
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
