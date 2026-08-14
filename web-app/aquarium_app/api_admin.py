from __future__ import annotations

import sqlite3
from datetime import datetime
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from .deps import csrf_protect, get_store, remote_addr, require_roles
from .models import (
    AlarmComplete,
    AlarmCreate,
    CleanupRequest,
    CommandCreate,
    DeviceKeyCreate,
    DeviceUpsert,
    ScheduleUpsert,
    SettingsUpdate,
    UserCreate,
    UserUpdate,
)
from .store import Store


router = APIRouter(prefix="/api/v1/manage", tags=["management"])


def _audit_user(
    store: Store,
    request: Request,
    user: dict[str, Any],
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    store.audit(
        actor_type="user",
        actor_id=str(user["id"]),
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        remote_addr=remote_addr(request),
    )


@router.get("/devices")
def list_devices(
    _: dict[str, Any] = Depends(require_roles("viewer", "operator", "admin")),
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    return store.list_devices()


@router.put("/devices/{device_id}")
def put_device(
    device_id: str,
    payload: DeviceUpsert,
    request: Request,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    data = payload.model_dump()
    if data["id"] != device_id:
        raise HTTPException(status_code=400, detail="device id mismatch")
    device = store.upsert_device(data)
    _audit_user(store, request, user, "device.upsert", "device", device_id)
    return device


@router.get("/device-keys")
def list_keys(
    device_id: str | None = None,
    _: dict[str, Any] = Depends(require_roles("admin")),
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    return store.list_device_keys(device_id)


@router.post("/devices/{device_id}/keys")
def create_key(
    device_id: str,
    payload: DeviceKeyCreate,
    request: Request,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, str]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    try:
        result = store.create_device_key(device_id, payload.label)
    except KeyError:
        raise HTTPException(status_code=404, detail="device not found") from None
    _audit_user(store, request, user, "device-key.create", "device", device_id, {"key_id": result["key_id"]})
    return result


@router.delete("/device-keys/{key_id}")
def revoke_key(
    key_id: str,
    request: Request,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, bool]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    if not store.revoke_device_key(key_id):
        raise HTTPException(status_code=404, detail="key not found")
    _audit_user(store, request, user, "device-key.revoke", "device-key", key_id)
    return {"ok": True}


@router.get("/commands")
def list_commands(
    device_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: dict[str, Any] = Depends(require_roles("viewer", "operator", "admin")),
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    return store.list_commands(device_id=device_id, limit=limit)


@router.post("/devices/{device_id}/commands")
def create_command(
    device_id: str,
    payload: CommandCreate,
    request: Request,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if user["role"] not in {"operator", "admin"}:
        raise HTTPException(status_code=403, detail="operator or admin required")
    try:
        command = store.create_command(
            device_id=device_id,
            command=payload.command,
            parameters=payload.parameters,
            requested_by=user["id"],
            deliver_after=payload.deliver_after,
            expires_in_seconds=payload.expires_in_seconds,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="device not found or disabled") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_user(store, request, user, "command.create", "command", command["id"], {"device_id": device_id})
    return command


@router.delete("/commands/{command_id}")
def cancel_command(
    command_id: str,
    request: Request,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if user["role"] not in {"operator", "admin"}:
        raise HTTPException(status_code=403, detail="operator or admin required")
    command = store.cancel_command(command_id)
    if not command:
        raise HTTPException(status_code=404, detail="command not found")
    _audit_user(store, request, user, "command.cancel", "command", command_id)
    return command


@router.get("/schedules")
def list_schedules(
    device_id: str | None = None,
    _: dict[str, Any] = Depends(require_roles("viewer", "operator", "admin")),
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    return store.list_schedules(device_id)


@router.put("/schedules")
def put_schedule(
    payload: ScheduleUpsert,
    request: Request,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if user["role"] not in {"operator", "admin"}:
        raise HTTPException(status_code=403, detail="operator or admin required")
    if not store.get_device(payload.device_id):
        raise HTTPException(status_code=404, detail="device not found")
    schedule = store.upsert_schedule(payload.model_dump(), user["id"])
    _audit_user(store, request, user, "schedule.upsert", "schedule", str(schedule["id"]))
    return schedule


@router.delete("/schedules/{schedule_id}")
def delete_schedule(
    schedule_id: int,
    request: Request,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, bool]:
    if user["role"] not in {"operator", "admin"}:
        raise HTTPException(status_code=403, detail="operator or admin required")
    if not store.delete_schedule(schedule_id):
        raise HTTPException(status_code=404, detail="schedule not found")
    _audit_user(store, request, user, "schedule.delete", "schedule", str(schedule_id))
    return {"ok": True}


@router.get("/settings")
def settings(
    _: dict[str, Any] = Depends(require_roles("viewer", "operator", "admin")),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return store.get_settings()


@router.patch("/settings")
def patch_settings(
    payload: SettingsUpdate,
    request: Request,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    updated = store.update_settings(payload.provided(), user["id"])
    _audit_user(store, request, user, "settings.update", "settings", detail=payload.provided())
    return updated


@router.get("/database")
def database_stats(
    _: dict[str, Any] = Depends(require_roles("admin")),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    return store.database_stats()


@router.post("/database/cleanup")
def database_cleanup(
    payload: CleanupRequest,
    request: Request,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    result = store.cleanup(payload.retention_days, vacuum=payload.vacuum)
    _audit_user(store, request, user, "database.cleanup", "database", detail=result["deleted"])
    return result


@router.get("/database/export")
def database_export(
    _: dict[str, Any] = Depends(require_roles("admin")),
    store: Store = Depends(get_store),
) -> StreamingResponse:
    filename = f"aquarium-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    return StreamingResponse(
        BytesIO(store.export_zip()),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/users")
def users(
    _: dict[str, Any] = Depends(require_roles("admin")),
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    return store.list_users()


@router.post("/users")
def create_user(
    payload: UserCreate,
    request: Request,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    try:
        created = store.create_user(payload.username, payload.password, payload.role)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="username already exists") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit_user(store, request, user, "user.create", "user", str(created["id"]), {"role": created["role"]})
    return created


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    if user_id == user["id"] and payload.active is False:
        raise HTTPException(status_code=400, detail="cannot disable the active account")
    result = store.update_user(user_id, role=payload.role, active=payload.active)
    if not result:
        raise HTTPException(status_code=404, detail="user not found")
    if payload.password:
        store.set_password(user_id, payload.password)
    _audit_user(store, request, user, "user.update", "user", str(user_id), payload.model_dump(exclude_none=True, exclude={"password"}))
    return store.get_user(user_id)


@router.get("/audit")
def audit_log(
    limit: int = Query(default=200, ge=1, le=1000),
    _: dict[str, Any] = Depends(require_roles("admin")),
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    return store.list_audit(limit)


@router.post("/alarms")
def create_alarm(
    payload: AlarmCreate,
    request: Request,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if user["role"] not in {"operator", "admin"}:
        raise HTTPException(status_code=403, detail="operator or admin required")
    if not store.get_settings()["alarm_api_enabled"]:
        raise HTTPException(status_code=409, detail="alarm API is disabled")
    alarm = store.enqueue_alarm(**payload.model_dump())
    _audit_user(store, request, user, "alarm.enqueue", "alarm", alarm["id"])
    return alarm


@router.post("/alarms/claim")
def claim_alarms(
    limit: int = Query(default=20, ge=1, le=100),
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    if user["role"] not in {"operator", "admin"}:
        raise HTTPException(status_code=403, detail="operator or admin required")
    return store.claim_alarms(limit)


@router.post("/alarms/{alarm_id}/complete")
def complete_alarm(
    alarm_id: str,
    payload: AlarmComplete,
    user: dict[str, Any] = Depends(csrf_protect),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    if user["role"] not in {"operator", "admin"}:
        raise HTTPException(status_code=403, detail="operator or admin required")
    alarm = store.complete_alarm(alarm_id, sent=payload.sent, result=payload.result)
    if not alarm:
        raise HTTPException(status_code=404, detail="alarm not found")
    return alarm
