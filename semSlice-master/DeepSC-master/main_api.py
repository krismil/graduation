import uvicorn
from fastapi import FastAPI, HTTPException
from typing import List, Dict
# ... imports ...
from schemas import AllocationRequest

# 引入我们之前写的模块
from schemas import (
    NetworkConfig,
    SliceProfile,
    ServiceRequest,
    MatchResult,
    AllocationResult
)
from matcher import SemanticSliceMatcher
from allocator import ResourceAllocator

app = FastAPI(title="Semantic Slicing System Backend")

# =======================
# 全局状态存储 (内存数据库)
# =======================
# 在实际生产环境中，这些应该存入 Redis 或 SQL 数据库
# 但为了演示系统，用全局变量即可
SYSTEM_STATE = {
    "network_config": None,  # 当前网络配置
    "slices": [],  # 当前已配置的切片列表
    "active_matches": [],  # 当前业务与切片的匹配结果
    "latest_allocation": []  # 最近一次资源分配结果
}

# =======================
# 系统初始化
# =======================
# 预定义领域与词表的映射关系
# 请确保这些路径下有对应的 json 文件，或者修改为你实际的文件路径
DOMAIN_VOCAB_MAP = {
    "animal": "./checkpoints/vocab_animal.json",
    "music": "./checkpoints/vocab_music.json",
    "sports": "./checkpoints/vocab_sports.json",
    "general": "./checkpoints/vocab_en.json"  # 默认通用
}

# 初始化匹配器实例
matcher_service = SemanticSliceMatcher(DOMAIN_VOCAB_MAP)


# =======================
# API 接口定义
# =======================

@app.get("/")
def read_root():
    return {"status": "System Online", "version": "1.0"}


# -----------------------
# 1. 网络配置接口
# -----------------------
@app.post("/config/network", response_model=Dict[str, str])
def configure_network(config: NetworkConfig):
    """
    接收前端发来的网络配置（带宽、功率、信道模型等）
    """
    SYSTEM_STATE["network_config"] = config
    return {"message": "Network configuration updated successfully"}


# -----------------------
# 2. 切片配置接口
# -----------------------
@app.post("/config/slices", response_model=Dict[str, int])
def configure_slices(slices: List[SliceProfile]):
    """
    接收前端配置的切片列表
    """
    SYSTEM_STATE["slices"] = slices
    # 清空之前的匹配状态，因为切片变了
    SYSTEM_STATE["active_matches"] = []
    return {"message": "Slices configured", "count": len(slices)}


# -----------------------
# 3. 业务匹配接口 (Step 4 in logic)
# -----------------------


@app.post("/services/match", response_model=List[MatchResult])
def match_services(services: List[ServiceRequest], strategy: str = "semantic"):
    """
    Query Param: strategy = semantic | network | none
    """
    # 存入状态
    SYSTEM_STATE["current_strategy"] = strategy

    # 传统切片也需要 slice 信息来做随机匹配
    results = matcher_service.match_services(services, SYSTEM_STATE["slices"], strategy=strategy)
    SYSTEM_STATE["active_matches"] = results
    return results


@app.post("/resources/allocate", response_model=List[AllocationResult])
def allocate_resources(request: AllocationRequest):
    """
    Body: { "strategy": "semantic" }
    """
    allocator = ResourceAllocator(SYSTEM_STATE["network_config"])

    # 使用前端传来的策略，确保匹配和分配使用同一逻辑
    results = allocator.execute_allocation(SYSTEM_STATE["active_matches"], strategy=request.strategy)

    SYSTEM_STATE["latest_allocation"] = results
    return results

# -----------------------
# 辅助接口：获取当前系统快照 (用于前端仪表盘实时刷新)
# -----------------------
@app.get("/system/status")
def get_system_status():
    return {
        "network_configured": SYSTEM_STATE["network_config"] is not None,
        "slice_count": len(SYSTEM_STATE["slices"]),
        "active_service_count": len(SYSTEM_STATE["active_matches"]),
        "allocation_done": len(SYSTEM_STATE["latest_allocation"]) > 0
    }


# =======================
# 启动入口
# =======================
if __name__ == "__main__":
    # 运行服务器，监听 8000 端口
    # reload=True 表示代码修改后自动重启，方便调试
    uvicorn.run("main_api:app", host="0.0.0.0", port=8000, reload=True)