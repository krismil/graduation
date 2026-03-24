import re
import secrets
from typing import Dict, List, Optional

from fastapi import Header, HTTPException

from app.models.schemas import LoginRequest, LoginResponse


USERS = {
    "admin": {"password": "admin123", "role": "admin", "tenant_id": None},
    "tenant1": {"password": "tenant123", "role": "tenant", "tenant_id": "tenant-1"},
    "tenant2": {"password": "tenant123", "role": "tenant", "tenant_id": "tenant-2"},
}

SESSIONS = {}


def _dynamic_tenant_account(username: str) -> Optional[Dict[str, Optional[str]]]:
    match = re.fullmatch(r"tenant(\d+)", username or "")
    if not match:
        return None
    idx = int(match.group(1))
    if idx <= 0:
        return None
    return {"password": "tenant123", "role": "tenant", "tenant_id": f"tenant-{idx}"}


def login(payload: LoginRequest) -> LoginResponse:
    account = USERS.get(payload.username)
    if account is None:
        dynamic = _dynamic_tenant_account(payload.username)
        if dynamic is not None:
            USERS[payload.username] = dynamic
            account = dynamic
    if account is None or account.get("password") != payload.password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if payload.system_type == "admin" and account.get("role") != "admin":
        raise HTTPException(status_code=403, detail="当前账号不是管理员")
    if payload.system_type == "tenant" and account.get("role") != "tenant":
        raise HTTPException(status_code=403, detail="当前账号不是租户")

    token = secrets.token_urlsafe(24)
    user_ctx = {
        "username": payload.username,
        "role": account["role"],
        "tenant_id": account.get("tenant_id"),
    }
    SESSIONS[token] = user_ctx
    home = "/admin/dashboard" if account["role"] == "admin" else "/tenant/dashboard"
    return LoginResponse(
        token=token,
        role=account["role"],
        username=payload.username,
        tenant_id=account.get("tenant_id"),
        system_home=home,
    )


def logout(token: str) -> None:
    if token in SESSIONS:
        SESSIONS.pop(token)


def _parse_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少 Authorization 头")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization 格式错误")
    return authorization.split(" ", 1)[1].strip()


def get_current_user(authorization: str = Header(None)) -> Dict[str, Optional[str]]:
    token = _parse_token(authorization)
    user = SESSIONS.get(token)
    if user is None:
        raise HTTPException(status_code=401, detail="登录已过期")
    return user


def ensure_role(user: Dict[str, Optional[str]], allowed_roles: List[str]) -> None:
    if user.get("role") not in allowed_roles:
        raise HTTPException(status_code=403, detail="权限不足")


def extract_token_from_header(authorization: Optional[str]) -> str:
    return _parse_token(authorization)


def get_auth_stats() -> Dict[str, object]:
    sessions = list(SESSIONS.values())
    active_usernames = sorted(set(user.get("username") for user in sessions if user.get("username")))
    active_tenant_ids = sorted(set(user.get("tenant_id") for user in sessions if user.get("tenant_id")))
    return {
        "active_session_count": len(SESSIONS),
        "active_user_count": len(active_usernames),
        "active_tenant_count": len(active_tenant_ids),
        "active_users": active_usernames,
        "active_tenants": active_tenant_ids,
    }
