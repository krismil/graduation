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
VOCAB_SLICE_TAGS = ["en", "en90", "en80"]
VOCAB_SLICE_NAMES = ["slice-en", "slice-en90", "slice-en80"]


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
        KnowledgeBaseConfig(kb_id="kb-vocab-en", kb_type="vocab_en", knowledge_level=1.0),
        KnowledgeBaseConfig(kb_id="kb-vocab-en90", kb_type="vocab_en90", knowledge_level=0.9),
        KnowledgeBaseConfig(kb_id="kb-vocab-en80", kb_type="vocab_en80", knowledge_level=0.8),
    ]


def _norm(text: str) -> str:
    return str(text or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _infer_vocab_tag(text: str) -> str:
    token = _norm(text)
    if "90" in token:
        return "en90"
    if "80" in token:
        return "en80"
    if "en" in token:
        return "en"
    return "en"


def _normalize_vocab_knowledge_bases(items: List[KnowledgeBaseConfig]) -> List[KnowledgeBaseConfig]:
    defaults = {
        "en": KnowledgeBaseConfig(kb_id="kb-vocab-en", kb_type="vocab_en", knowledge_level=1.0),
        "en90": KnowledgeBaseConfig(kb_id="kb-vocab-en90", kb_type="vocab_en90", knowledge_level=0.9),
        "en80": KnowledgeBaseConfig(kb_id="kb-vocab-en80", kb_type="vocab_en80", knowledge_level=0.8),
    }
    if not items:
        return [defaults["en"], defaults["en90"], defaults["en80"]]

    selected = dict(defaults)
    for kb in items:
        tag = _infer_vocab_tag("{0} {1}".format(kb.kb_type, kb.kb_id))
        selected[tag] = KnowledgeBaseConfig(
            kb_id=kb.kb_id,
            kb_type=kb.kb_type,
            knowledge_level=float(kb.knowledge_level),
        )
    return [selected["en"], selected["en90"], selected["en80"]]


def build_slice_config(config: SliceConfigRequest) -> SliceConfigResponse:
    knowledge_bases = _normalize_vocab_knowledge_bases(config.knowledge_bases if config.knowledge_bases else _default_knowledge_bases())
    fixed_slice_count = 3

    codecs: List[CodecConfig] = []
    codec_count = max(int(config.codec_count), fixed_slice_count)
    for idx in range(codec_count):
        kb = knowledge_bases[idx % len(knowledge_bases)]
        codecs.append(
            CodecConfig(
                codec_id="codec-{0}".format(idx + 1),
                modality="text",
                kb_id=kb.kb_id,
            )
        )

    slices: List[SliceInstance] = []
    for idx in range(fixed_slice_count):
        kb = knowledge_bases[idx]
        codec = codecs[idx % len(codecs)]
        name = config.slice_names[idx] if idx < len(config.slice_names) else VOCAB_SLICE_NAMES[idx]
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
