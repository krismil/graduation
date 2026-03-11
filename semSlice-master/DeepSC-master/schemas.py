# schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

# =======================
# 定义策略枚举
# =======================
class StrategyType(str, Enum):
    SEMANTIC = "semantic"   # 语义切片 (你的算法，性能最优)
    NETWORK = "network"     # 传统网络切片 (传统香农，性能中等)
    NONE = "none"           # 无切片 (大锅饭，性能最差)

# =======================
# 1. 业务配置 (Service Configuration)
# =======================
class ServiceRequest(BaseModel):
    service_id: str
    domain: str
    requirement_type: str  # 确保这里和前端 js 里的 key 一致
    priority: int = 1

# =======================
# 2. 网络配置 (Network Configuration)
# =======================
class NetworkConfig(BaseModel):
    cpu_capacity: float = Field(..., description="CPU处理能力 (GHz/Ops)")
    energy_threshold: float = Field(..., description="计算能耗阈值 (J)")
    total_bandwidth: float = Field(..., description="总带宽 (MHz)", example=2.0)
    total_power: float = Field(..., description="总功率 (W)", example=1.0)
    channel_model: str = Field("AWGN", description="信道模型: AWGN, Rayleigh, Rician")
    snr_db: float = Field(10.0, description="当前环境的基础信噪比 (dB)")

# =======================
# 3. 切片配置 (Slice Configuration)
# =======================
class CodecConfig(BaseModel):
    codec_type: str = Field(..., description="编解码器类型", example="deepsc_text")
    deployment_level: str = Field("full", description="知识库部署程度: full, lite")
    kb_type: str = Field(..., description="知识库类型", example="sports_kb")

class SliceProfile(BaseModel):
    slice_id: str = Field(..., description="切片ID")
    slice_name: str = Field(..., description="切片命名")
    codecs: List[CodecConfig] = Field(..., description="该切片部署的编解码器列表")
    checkpoint_path: Optional[str] = Field(None, description="模型权重文件路径")
    vocab_path: Optional[str] = Field(None, description="词表文件路径")

# =======================
# 4. API 请求与输出模型 (Request & Output Models)
# =======================
class AllocationRequest(BaseModel):
    strategy: StrategyType = Field(..., description="资源分配策略: semantic, network, none")

class MatchResult(BaseModel):
    service_id: str
    slice_id: str
    matched_domain: str
    similarity_score: float
    status: str = "matched"

class AllocationResult(BaseModel):
    mode: StrategyType = Field(..., description="当前结果的策略类型")
    service_id: str
    slice_id: str
    assigned_power: float
    assigned_bandwidth: float
    estimated_delay: float
    estimated_energy: float = Field(0.0, description="预估能耗 (J) = 功率 * 时延") # 新增能耗
    estimated_s_se: float     
    similarity_score: float = Field(0.0, description="最终的内容相似度/保真度")