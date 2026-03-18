﻿# Frontend

前端已升级为六模块系统页面：

1. 业务配置
2. 网络配置
3. 切片配置
4. 切片与业务适配
5. 资源分配与性能评估
6. 管理员/租户登录

## 运行

```bash
cd frontend
python -m http.server 5173
```

浏览器访问 `http://127.0.0.1:5173`。

默认后端地址：`http://127.0.0.1:8000/api/v1`。

## 默认账号

- 管理员：`admin / admin123`
- 租户：`tenant1 / tenant123`

## 分配后端

- `online_pso`：当前在线编排 PSO（默认）
- `legacy_experiment`：调用原仓库 `main_compute` 作为适应度评估的严格复现实验后端
