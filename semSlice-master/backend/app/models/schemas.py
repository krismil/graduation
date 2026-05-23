from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field


TaskType = str
SliceStrategy = str


class ServiceProfile(BaseModel):
    service_id: str = Field(..., description="Business identifier")
    task_type: TaskType = "HF"
    semantic_nssai: float = Field(..., ge=0, le=100)
    request_bandwidth: float = Field(..., gt=0, description="MHz")
    payload_symbols: int = Field(10, ge=1)
    distance_m: float = Field(3000, gt=0)
    base_similarity: float = Field(0.72, ge=0, le=1)


class SemanticProcessRequest(BaseModel):
    services: List[ServiceProfile]
    noise_dbm: float = -114.45


class SemanticResultItem(BaseModel):
    service_id: str
    encoder_level: int
    snr_db: float
    semantic_fidelity: float
    tx_delay_ms: float


class SemanticProcessResponse(BaseModel):
    items: List[SemanticResultItem]
    summary: Dict[str, float]


class SliceQoS(BaseModel):
    target_similarity: float
    target_delay_ms: float


class SliceDefinition(BaseModel):
    slice_id: str
    encoder_level: int
    members: List[str]
    qos: SliceQoS


class SliceBuildRequest(BaseModel):
    services: List[ServiceProfile]
    strategy: SliceStrategy = "semantic"


class SliceBuildResponse(BaseModel):
    slices: List[SliceDefinition]
    assignment: Dict[str, str]


class ResourceState(BaseModel):
    total_power: float = Field(1.0, gt=0)
    total_bandwidth: float = Field(2.0, gt=0)
    congestion_level: float = Field(0.0, ge=0, le=1)


class ResourceAllocationItem(BaseModel):
    slice_id: str
    power: float
    bandwidth: float


class OrchestrationRequest(BaseModel):
    services: List[ServiceProfile]
    slices: List[SliceDefinition]
    network_state: ResourceState = Field(default_factory=ResourceState)


class OrchestrationResponse(BaseModel):
    allocations: List[ResourceAllocationItem]
    remaining: Dict[str, float]


class EvaluationRequest(BaseModel):
    services: List[ServiceProfile]
    semantic_results: List[SemanticResultItem]
    assignment: Dict[str, str]
    allocations: List[ResourceAllocationItem]


class EvaluationResponse(BaseModel):
    core_metrics: Dict[str, float]
    service_metrics: List[Dict[str, Union[float, str, bool]]]
    chart_data: Dict[str, List[Dict[str, Union[float, str]]]]


class WorkflowRequest(BaseModel):
    services: List[ServiceProfile]
    strategy: SliceStrategy = "semantic"
    network_state: ResourceState = Field(default_factory=ResourceState)


class WorkflowResponse(BaseModel):
    semantic: SemanticProcessResponse
    slicing: SliceBuildResponse
    orchestration: OrchestrationResponse
    evaluation: EvaluationResponse


class LegacyStrategyCompareRequest(BaseModel):
    scenario: str = "fitSNR"
    resource_vector: List[float] = Field(default_factory=lambda: [0.2, 0.3, 0.5, 0.6, 0.8, 0.6])


class LegacyStrategyPoint(BaseModel):
    task_id: int
    delay_ms: float
    ss: float
    s_se: float


class LegacyStrategySummary(BaseModel):
    strategy: str
    score_sum: Optional[float] = None
    score_by_slice: List[float] = Field(default_factory=list)
    avg_delay_ms: Optional[float] = None
    avg_ss: Optional[float] = None
    avg_s_se: Optional[float] = None
    points: List[LegacyStrategyPoint] = Field(default_factory=list)
    error: Optional[str] = None


class LegacyStrategyCompareResponse(BaseModel):
    success: bool
    scenario: str
    resource_vector: List[float]
    comparisons: List[LegacyStrategySummary]


class LoginRequest(BaseModel):
    username: str
    password: str
    system_type: str = "user"


class LoginResponse(BaseModel):
    token: str
    role: str
    username: str
    user_id: Optional[int] = None
    system_home: str


class UserBusinessItem(BaseModel):
    user_id: str
    modality: str = "text"
    requirement_type: str = "high_fidelity"
    domain_type: str = "generic"
    payload_symbols: int = Field(10, ge=1)
    distance_m: float = Field(3000, gt=0)
    base_similarity: float = Field(0.72, ge=0, le=1)
    task_pkl: Optional[str] = None
    task_vocab: Optional[str] = None
    sample_index: int = Field(0, ge=0)


class BusinessConfig(BaseModel):
    user_count: int = Field(3, ge=1)
    modality: str = "text"
    default_requirement_type: str = "high_fidelity"
    default_domain_type: str = "generic"
    users: List[UserBusinessItem] = Field(default_factory=list)


class BusinessConfigResponse(BaseModel):
    users: List[UserBusinessItem]
    summary: Dict[str, Union[int, str, float]]


class NetworkConfig(BaseModel):
    total_bandwidth: float = Field(2.0, gt=0)
    total_power: float = Field(1.0, gt=0)
    target_snr_db: float = Field(6.0, ge=-20.0, le=30.0)
    node_count: int = Field(5, ge=1)
    base_station_count: int = Field(1, ge=1)
    channel_scenario: Optional[str] = None


class NetworkConfigResponse(BaseModel):
    network: Dict[str, Union[float, int, str]]


class KnowledgeBaseConfig(BaseModel):
    kb_id: str
    kb_type: str
    knowledge_level: float = Field(0.8, ge=0, le=1)


class CodecConfig(BaseModel):
    codec_id: str
    modality: str = "text"
    kb_id: str


class SliceInstance(BaseModel):
    slice_id: str
    slice_name: str
    codec_id: str
    modality: str
    kb_id: str
    kb_type: str
    knowledge_level: float


class SliceConfigRequest(BaseModel):
    slice_count: int = Field(3, ge=1)
    slice_names: List[str] = Field(default_factory=list)
    codec_count: int = Field(3, ge=1)
    codec_modality: str = "text"
    knowledge_bases: List[KnowledgeBaseConfig] = Field(default_factory=list)


class SliceConfigResponse(BaseModel):
    slices: List[SliceInstance]
    codecs: List[CodecConfig]


class AdaptationRequest(BaseModel):
    users: List[UserBusinessItem]
    slices: List[SliceInstance]
    method: str = "similarity"


class AdaptationRow(BaseModel):
    user_id: str
    domain_type: str
    requirement_type: str
    matched_slice_id: str
    matched_slice_name: str
    codec_id: str
    kb_id: str
    similarity_score: float


class AdaptationResponse(BaseModel):
    relations: List[AdaptationRow]


class UserResourceAllocation(BaseModel):
    user_id: str
    slice_id: str
    bandwidth: float
    power: float


class ResourceAllocationRequestV2(BaseModel):
    users: List[UserBusinessItem]
    relations: List[AdaptationRow]
    network: NetworkConfig
    algorithm: str = "semslice"


class ResourceAllocationResponseV2(BaseModel):
    allocations: List[UserResourceAllocation]
    used_resources: Dict[str, float]
    remaining_resources: Dict[str, float]
    timeline: List[Dict[str, float]]


class PerformanceEvaluateRequest(BaseModel):
    users: List[UserBusinessItem]
    allocations: List[UserResourceAllocation]
    network: NetworkConfig
    relations: List[AdaptationRow] = Field(default_factory=list)
    allocation_algorithm: str = "semslice"


class PerformanceEvaluateResponse(BaseModel):
    core_metrics: Dict[str, float]
    user_metrics: List[Dict[str, Union[str, float, bool]]]
    charts: Dict[str, List[Dict[str, Union[str, float]]]]


class FullSystemRequest(BaseModel):
    business: BusinessConfig
    network: NetworkConfig
    slicing: SliceConfigRequest
    adaptation_method: str = "similarity"
    allocation_algorithm: str = "semslice"


class FullSystemResponse(BaseModel):
    business_output: BusinessConfigResponse
    network_output: NetworkConfigResponse
    slicing_output: SliceConfigResponse
    adaptation_output: AdaptationResponse
    allocation_output: ResourceAllocationResponseV2
    performance_output: PerformanceEvaluateResponse


class WorkflowState(BaseModel):
    last_run: Optional[WorkflowResponse] = None
    last_new_run: Optional[FullSystemResponse] = None
    network_configured: bool = False
    slicing_configured: bool = False
    admin_config_ready: bool = False
    strategy_runs: Dict[str, FullSystemResponse] = Field(default_factory=dict)
    strategy_boards: Dict[str, List[Dict[str, Union[str, float, bool]]]] = Field(default_factory=dict)
    admin_task_board: List[Dict[str, Union[str, float, bool]]] = Field(default_factory=list)
    pending_tasks: List[Dict[str, Union[str, float, bool, int]]] = Field(default_factory=list)
