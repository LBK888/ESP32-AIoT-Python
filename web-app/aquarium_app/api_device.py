from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .deps import get_store, remote_addr, require_device
from .models import CommandAck, DeviceEventCreate, TelemetryBatch
from .store import Store


router = APIRouter(prefix="/api/v1/device", tags=["device"])


@router.get("/config")
def device_config(
    device: dict[str, Any] = Depends(require_device),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    record = store.get_device(device["id"])
    schedules = store.list_schedules(device["id"])
    return {
        "device_id": device["id"],
        "enabled": record["enabled"],
        "settings": record["settings"],
        "schedules": schedules,
        "poll_seconds": 5,
        "control_authority": "local-safety-first",
    }


@router.post("/telemetry")
def telemetry(
    payload: TelemetryBatch,
    request: Request,
    device: dict[str, Any] = Depends(require_device),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    count = store.ingest_readings(
        device["id"],
        [reading.model_dump() for reading in payload.readings],
        payload.ts,
        payload.metadata,
    )
    store.audit(
        actor_type="device",
        actor_id=device["id"],
        action="telemetry.ingest",
        target_type="readings",
        detail={"count": count},
        remote_addr=remote_addr(request),
    )
    return {"accepted": count, "device_id": device["id"]}


@router.post("/events")
def device_event(
    payload: DeviceEventCreate,
    request: Request,
    device: dict[str, Any] = Depends(require_device),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    event = store.create_event(
        device_id=device["id"],
        event_type=payload.event_type,
        severity=payload.severity,
        title=payload.title,
        detail=payload.detail,
        occurred_at=payload.ts,
        scheduled_for=payload.scheduled_for,
        source="device",
        payload=payload.payload,
    )
    if payload.severity in {"warning", "danger"} and store.get_settings()["alarm_api_enabled"]:
        store.enqueue_alarm(
            alarm_type=payload.event_type,
            severity=payload.severity,
            title=payload.title,
            message=payload.detail or payload.title,
            payload={"device_id": device["id"], "event_id": event["id"], **payload.payload},
        )
    store.audit(
        actor_type="device",
        actor_id=device["id"],
        action="event.create",
        target_type="event",
        target_id=str(event["id"]),
        remote_addr=remote_addr(request),
    )
    return event


@router.get("/commands/next")
def next_command(
    device: dict[str, Any] = Depends(require_device),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    command = store.next_command(device["id"])
    return {"command": command}


@router.post("/commands/{command_id}/ack")
def acknowledge(
    command_id: str,
    payload: CommandAck,
    request: Request,
    device: dict[str, Any] = Depends(require_device),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    command = store.acknowledge_command(
        device_id=device["id"],
        command_id=command_id,
        success=payload.success,
        result=payload.result,
    )
    if not command:
        raise HTTPException(status_code=404, detail="command not found or already completed")
    store.audit(
        actor_type="device",
        actor_id=device["id"],
        action="command.acknowledge",
        target_type="command",
        target_id=command_id,
        detail={"success": payload.success},
        remote_addr=remote_addr(request),
    )
    return command

