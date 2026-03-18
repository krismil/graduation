﻿# Backend (FastAPI)

## 新增能力

- 管理员/租户双系统登录（Token 鉴权）
- 业务配置：用户数、文本模态、需求类型、领域类型
- 网络配置：CPU、能耗阈值、总带宽、总功率、信道场景
- 切片配置：切片数、命名、编解码器、知识库
- 切片-业务适配：相似度或领域匹配
- 资源分配：`pso`（在线） / `weighted` / `equal` / `latency_first`
- 可选分配后端：`online_pso` / `legacy_experiment`
- 性能评估：保真度、时延、通过率、能耗

## `legacy_experiment` 参数

- `legacy_strategy`: `semslice` | `netslice`
- `legacy_scenario`: `fitSNR` | `fit5TASK` | `fit15TASK`
- `legacy_iterations`: 迭代轮数（默认 2）
- `legacy_particles`: 粒子数（默认 2）

## 默认账号

- 管理员：`admin / admin123`
- 租户1：`tenant1 / tenant123`
- 租户2：`tenant2 / tenant123`

## 运行

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 主要接口

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `POST /api/v1/module/business/config`
- `POST /api/v1/module/network/config`（管理员）
- `POST /api/v1/module/slice/config`（管理员）
- `POST /api/v1/module/adaptation`
- `POST /api/v1/module/resources/allocate`
- `POST /api/v1/module/performance/evaluate`
- `POST /api/v1/system/admin/run`（管理员）
- `POST /api/v1/system/tenant/run`
