from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from .deps import SESSION_COOKIE, csrf_protect, get_store, optional_user, remote_addr
from .models import LoginRequest
from .store import Store


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, store: Store = Depends(get_store)) -> dict[str, Any]:
    user = store.authenticate_user(payload.username, payload.password)
    if not user:
        store.audit(
            actor_type="anonymous",
            actor_id=payload.username,
            action="login.failed",
            remote_addr=remote_addr(request),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid username or password")
    token, csrf, expires_at = store.create_session(user["id"], remote_addr(request))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=store.settings.cookie_secure,
        samesite="strict",
        max_age=store.settings.session_hours * 3600,
        path="/",
    )
    store.audit(
        actor_type="user",
        actor_id=str(user["id"]),
        action="login.success",
        remote_addr=remote_addr(request),
    )
    return {"user": user, "csrf_token": csrf, "expires_at": expires_at}


@router.get("/me")
def me(user: dict[str, Any] | None = Depends(optional_user)) -> dict[str, Any]:
    if not user:
        return {"authenticated": False, "user": None, "csrf_token": None}
    safe_user = {key: user[key] for key in ("id", "username", "role")}
    return {"authenticated": True, "user": safe_user, "csrf_token": user["csrf_token"]}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, bool]:
    store.revoke_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    store.audit(actor_type="user", actor_id=str(user["id"]), action="logout", remote_addr=remote_addr(request))
    return {"ok": True}

