from typing import Dict, List, Optional

from fastapi import Header, HTTPException

from app.models.schemas import LoginRequest, LoginResponse
from app.store.repository import (
    create_session,
    delete_session,
    get_auth_stats as repo_get_auth_stats,
    get_session_user,
    get_user_by_username,
    verify_password,
)


def _normalize_system_type(raw: str) -> str:
    value = str(raw or "user").strip().lower()
    if value == "tenant":
        return "user"
    return value


def login(payload: LoginRequest) -> LoginResponse:
    account = get_user_by_username(payload.username)
    if account is None or account.get("status") != "active":
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(payload.password, str(account.get("password_hash", ""))):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    system_type = _normalize_system_type(payload.system_type)
    role = str(account.get("role"))

    if system_type == "admin" and role != "admin":
        raise HTTPException(status_code=403, detail="当前账号不是管理员")
    if system_type == "user" and role != "user":
        raise HTTPException(status_code=403, detail="当前账号不是普通用户")

    token = create_session(int(account["id"]))
    home = "/admin/dashboard" if role == "admin" else "/user/dashboard"
    return LoginResponse(
        token=token,
        role=role,
        username=str(account["username"]),
        user_id=int(account["id"]),
        system_home=home,
    )


def logout(token: str) -> None:
    delete_session(token)


def _parse_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少 Authorization 头")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization 格式错误")
    return authorization.split(" ", 1)[1].strip()


def get_current_user(authorization: str = Header(None)) -> Dict[str, Optional[str]]:
    token = _parse_token(authorization)
    user = get_session_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="登录已过期")
    return user


def ensure_role(user: Dict[str, Optional[str]], allowed_roles: List[str]) -> None:
    if user.get("role") not in allowed_roles:
        raise HTTPException(status_code=403, detail="权限不足")


def extract_token_from_header(authorization: Optional[str]) -> str:
    return _parse_token(authorization)


def get_auth_stats() -> Dict[str, object]:
    return repo_get_auth_stats()
