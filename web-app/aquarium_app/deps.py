from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, status

from .store import Store


SESSION_COOKIE = "aquarium_session"


def get_store(request: Request) -> Store:
    return request.app.state.store


def remote_addr(request: Request) -> str | None:
    return request.client.host if request.client else None


def optional_user(request: Request, store: Store = Depends(get_store)) -> dict[str, Any] | None:
    return store.get_session(request.cookies.get(SESSION_COOKIE))


def current_user(user: dict[str, Any] | None = Depends(optional_user)) -> dict[str, Any]:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")
    return user


def require_roles(*roles: str) -> Callable[..., dict[str, Any]]:
    def dependency(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient permission")
        return user

    return dependency


def csrf_protect(
    user: dict[str, Any] = Depends(current_user),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> dict[str, Any]:
    if not csrf_token or not hmac.compare_digest(csrf_token, user["csrf_token"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid CSRF token")
    return user


def require_device(
    request: Request,
    authorization: str | None = Header(default=None),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    device = store.authenticate_device(token)
    if not device:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid device API key")
    request.state.device = device
    return device

