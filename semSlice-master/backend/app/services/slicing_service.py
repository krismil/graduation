import random
from collections import defaultdict
from typing import Dict, List

from app.models.schemas import (
    CodecConfig,
    KnowledgeBaseConfig,
    ServiceProfile,
    SliceBuildResponse,
    SliceConfigRequest,
    SliceConfigResponse,
    SliceDefinition,
    SliceInstance,
    SliceQoS,
    SliceStrategy,
)
from app.services.semantic_service import select_encoder_level


RANDOM = random.Random(42)


def _slice_qos(task_types: List[str]) -> SliceQoS:
    if "RT" in task_types:
        return SliceQoS(target_similarity=0.6, target_delay_ms=110)
    if "HF" in task_types:
        return SliceQoS(target_similarity=0.7, target_delay_ms=180)
    return SliceQoS(target_similarity=0.55, target_delay_ms=220)


def _choose_slice(service: ServiceProfile, strategy: SliceStrategy) -> str:
    if strategy == "semantic":
        return "slice-{0}".format(select_encoder_level(service.semantic_nssai))
    if strategy == "random":
        return "slice-{0}".format(RANDOM.randint(1, 3))

    if service.task_type == "RT":
        return "slice-1"
    if service.semantic_nssai >= 90:
        return "slice-1"
    if service.semantic_nssai >= 80:
        return "slice-2"
    return "slice-3"


def build_and_distribute(services: List[ServiceProfile], strategy: SliceStrategy) -> SliceBuildResponse:
    grouped_members: Dict[str, List[str]] = defaultdict(list)
    grouped_types: Dict[str, List[str]] = defaultdict(list)
    assignment: Dict[str, str] = {}

    for service in services:
        slice_id = _choose_slice(service, strategy)
        grouped_members[slice_id].append(service.service_id)
        grouped_types[slice_id].append(service.task_type)
        assignment[service.service_id] = slice_id

    slices: List[SliceDefinition] = []
    for slice_id in sorted(grouped_members.keys()):
        encoder_level = int(slice_id.split("-")[-1])
        slices.append(
            SliceDefinition(
                slice_id=slice_id,
                encoder_level=encoder_level,
                members=grouped_members[slice_id],
                qos=_slice_qos(grouped_types[slice_id]),
            )
        )

    return SliceBuildResponse(slices=slices, assignment=assignment)


def _default_knowledge_bases() -> List[KnowledgeBaseConfig]:
    return [
        KnowledgeBaseConfig(kb_id="kb-animal", kb_type="animal", knowledge_level=0.92),
        KnowledgeBaseConfig(kb_id="kb-music", kb_type="music", knowledge_level=0.88),
        KnowledgeBaseConfig(kb_id="kb-sports", kb_type="sports", knowledge_level=0.86),
    ]


def build_slice_config(config: SliceConfigRequest) -> SliceConfigResponse:
    knowledge_bases = config.knowledge_bases if config.knowledge_bases else _default_knowledge_bases()

    codecs: List[CodecConfig] = []
    for idx in range(config.codec_count):
        kb = knowledge_bases[idx % len(knowledge_bases)]
        codecs.append(
            CodecConfig(
                codec_id="codec-{0}".format(idx + 1),
                modality="text",
                kb_id=kb.kb_id,
            )
        )

    slices: List[SliceInstance] = []
    for idx in range(config.slice_count):
        kb = knowledge_bases[idx % len(knowledge_bases)]
        codec = codecs[idx % len(codecs)]
        name = config.slice_names[idx] if idx < len(config.slice_names) else "Slice-{0}".format(idx + 1)
        slices.append(
            SliceInstance(
                slice_id="slice-{0}".format(idx + 1),
                slice_name=name,
                codec_id=codec.codec_id,
                modality="text",
                kb_id=kb.kb_id,
                kb_type=kb.kb_type,
                knowledge_level=kb.knowledge_level,
            )
        )

    return SliceConfigResponse(slices=slices, codecs=codecs)
