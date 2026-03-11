import uvicorn
import re
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict
from pydantic import BaseModel

from schemas import (
    NetworkConfig,
    SliceProfile,
    ServiceRequest,
    MatchResult,
    AllocationResult,
    AllocationRequest,
    StrategyType
)
from matcher import SemanticSliceMatcher
from allocator import ResourceAllocator

app = FastAPI(title="6G Intent-Driven Semantic Slicing System")

# ======== 跨域配置 (CORS) ========
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======== 全局状态与词表映射 ========
SYSTEM_STATE = {
    "network_config": None,
    "slices": [],
    "services": [],
    "active_matches": [],
    "latest_allocation": [],
    "current_strategy": "semantic"
}

# 🌟 修复后的行业级词表映射 (确保字典键名对齐)
DOMAIN_VOCAB_MAP = {
    "healthcare": "./checkpoint/vocab_en.json",  # 100% 词汇 (医疗要求最高)
    "industry": "./checkpoint/vocab_en90%.json",  # 90% 词汇 (工业环境)
    "city": "./checkpoint/vocab_en80%.json",  # 80% 词汇 (城市车联网)
    "general": "./checkpoint/vocab_en.json"
}

matcher_service = SemanticSliceMatcher(DOMAIN_VOCAB_MAP)


# ======== 🌟 6G 意图驱动 (IDN) 核心引擎 ========
class IntentRequest(BaseModel):
    text: str


# 启发式意图规则库
INTENT_RULES = {
    "domain": {
        "healthcare": ["医疗", "医生", "病人", "手术", "心电图", "超声", "病房", "x光", "mri", "监护", "救护车",
                       "健康"],
        "industry": ["工业", "制造", "工厂", "机械臂", "流水线", "传感器", "车间", "生产", "物联网", "机器人", "马达"],
        "city": ["城市", "交通", "红绿灯", "车联网", "监控", "自动驾驶", "安防", "摄像头", "公交", "车辆", "车祸",
                 "路口"]
    },
    "req_type": {
        "low_latency": ["紧急", "实时", "毫秒", "低延迟", "极速", "瞬时", "瞬态", "控制指令", "刹车", "警报", "立刻",
                        "立刻停", "危险"],
        "high_fidelity": ["高清", "无损", "精准", "清晰", "保真", "海量数据", "彩超", "细节", "画质", "文件", "高精度",
                          "完整"]
    }
}
# ==========================================
# 🌟 新增：用户系统与权限认证 (Mock DB)
# ==========================================
class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/auth/login")
def login(req: LoginRequest):
    """
    模拟多租户登录系统
    admin: 运营商管理员 (拥有全量物理网络调配权限)
    tenant: 垂直行业租户 (仅拥有意图驱动业务接入权限)
    """
    if req.username == "admin" and req.password == "123456":
        return {
            "token": "admin-token-6g-ops",
            "user": {"username": "中国移动(全局管理员)", "role": "admin", "avatar": "👑"}
        }
    elif req.username == "user" and req.password == "123456":
        return {
            "token": "tenant-token-health",
            "user": {"username": "协和医院(医疗租户)", "role": "tenant", "avatar": "🏥"}
        }
    else:
        raise HTTPException(status_code=401, detail="账号或密码错误")


@app.post("/services/analyze_intent")
def analyze_intent(req: IntentRequest):
    text = req.text
    if not text:
        raise HTTPException(status_code=400, detail="意图文本不能为空")

    # ==========================================
    # 🌟 1. 领域切片匹配 (Domain Classification)
    # ==========================================
    # 默认降级策略：如果什么都没匹配上，扔进“Smart_City”作为默认公共大网切片
    domain = "general"

    if any(keyword in text for keyword in ["医疗", "手术", "病房", "医生", "救护车"]):
        domain = "Smart_Healthcare"
    elif any(keyword in text for keyword in ["工业", "机械臂", "工厂", "流水线", "制造", "车间"]):
        domain = "Industrial_IoT"
    # 城市类关键词命中，或者默认兜底，都是 Smart_City
    elif any(keyword in text for keyword in ["城市", "交通", "监控", "街道", "红绿灯", "安防"]):
        domain = "general"

    # ==========================================
    # 🌟 2. QoS 约束特征提取 (QoS Extraction)
    # ==========================================
    # 默认降级策略：如果没有提到紧急或高清，默认走“standard (尽力而为/均衡传输)”
    req_type = "standard"

    # 优先级 1：低时延 (URLLC 级，时间极度敏感)
    if any(keyword in text for keyword in ["紧急", "实时", "控制", "立刻", "制动", "低时延", "报警", "故障"]):
        req_type = "low_latency"
    # 优先级 2：高保真 (eMBB 级，数据完整性敏感)
    elif any(keyword in text for keyword in ["高清", "4K", "视频", "影像", "高保真", "直播", "画面", "细节"]):
        req_type = "high_fidelity"

    return {
        "parsed_domain": domain,
        "parsed_req_type": req_type
    }


# ======== 标准 API 路由 ========
@app.get("/")
def read_root():
    return {"status": "System Online", "version": "2.0 (Intent-Driven)"}


@app.post("/config/network")
def configure_network(config: NetworkConfig):
    SYSTEM_STATE["network_config"] = config
    return {"message": "Network configuration updated"}


@app.post("/config/slices")
def configure_slices(slices: List[SliceProfile]):
    SYSTEM_STATE["slices"] = slices
    SYSTEM_STATE["active_matches"] = []
    return {"message": "Slices configured", "count": len(slices)}


@app.post("/services/match", response_model=List[MatchResult])
def match_services(services: List[ServiceRequest], strategy: StrategyType = StrategyType.SEMANTIC):
    SYSTEM_STATE["services"] = services
    SYSTEM_STATE["current_strategy"] = strategy.value

    results = matcher_service.match_services(services, SYSTEM_STATE["slices"], strategy=strategy.value)
    SYSTEM_STATE["active_matches"] = results
    return results


@app.post("/resources/allocate", response_model=List[AllocationResult])
def allocate_resources(request: AllocationRequest):
    if not SYSTEM_STATE["network_config"]:
        raise HTTPException(status_code=400, detail="Network not configured.")
    if not SYSTEM_STATE["active_matches"]:
        raise HTTPException(status_code=400, detail="No active matches found.")

    allocator = ResourceAllocator(SYSTEM_STATE["network_config"])
    results = allocator.execute_allocation(
        SYSTEM_STATE["active_matches"],
        strategy=request.strategy.value,
        services=SYSTEM_STATE["services"]
    )
    SYSTEM_STATE["latest_allocation"] = results
    return results


@app.get("/system/status")
def get_system_status():
    return {
        "network_configured": SYSTEM_STATE["network_config"] is not None,
        "slice_count": len(SYSTEM_STATE["slices"]),
        "active_service_count": len(SYSTEM_STATE["active_matches"]),
        "allocation_done": len(SYSTEM_STATE["latest_allocation"]) > 0
    }

if __name__ == "__main__":
    uvicorn.run("main_api:app", host="0.0.0.0", port=8000, reload=True)