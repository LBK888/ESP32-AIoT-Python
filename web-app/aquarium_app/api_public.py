from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from .deps import get_store
from .forecast import linear_forecast
from .store import Store, utc_now


router = APIRouter(prefix="/api/v1", tags=["public"])


@router.get("/health")
def health(store: Store = Depends(get_store)) -> dict[str, Any]:
    return {"status": "ok", "database": store.path.exists(), "version": "1.0.0"}


def _health_summary(devices: list[dict[str, Any]], readings: list[dict[str, Any]]) -> dict[str, Any]:
    score = 100
    counts = {"normal": 0, "warning": 0, "danger": 0, "missing": 0}
    for reading in readings:
        state = reading["status"]
        counts[state] = counts.get(state, 0) + 1
        score -= {"normal": 0, "warning": 4, "danger": 14, "missing": 7}.get(state, 3)
    offline = sum(1 for device in devices if device["enabled"] and device["status"] != "online")
    score -= offline * 3
    score = max(0, min(100, score))
    if not readings:
        score, state, title = 100, "empty", "等待第一筆感測資料"
    elif counts["danger"]:
        state, title = "danger", "魚缸有需要立即確認的異常"
    elif counts["warning"] or counts["missing"] or offline:
        state, title = "warning", "部分數據需要留意"
    else:
        state, title = "normal", "魚缸運作穩定"
    return {"score": score, "state": state, "title": title, "counts": counts, "offline_devices": offline}


@router.get("/dashboard")
def dashboard(store: Store = Depends(get_store)) -> dict[str, Any]:
    store.mark_offline_devices()
    devices = store.list_devices()
    readings = store.latest_readings()
    events = store.list_events(limit=30)
    settings = store.get_settings()
    return {
        "generated_at": utc_now().isoformat().replace("+00:00", "Z"),
        "health": _health_summary(devices, readings),
        "devices": devices,
        "readings": readings,
        "events": events,
        "public": bool(settings["public_dashboard"]),
        "refresh_seconds": settings["dashboard_refresh_seconds"],
    }


@router.get("/metrics")
def metrics(store: Store = Depends(get_store)) -> list[dict[str, Any]]:
    return store.metric_catalog()


@router.get("/history/{metric}")
def history(
    metric: str,
    hours: int = Query(default=24, ge=1, le=24 * 366 * 5),
    device_id: str | None = None,
    limit: int = Query(default=2000, ge=1, le=10000),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    since = utc_now() - timedelta(hours=hours)
    points = store.history(metric=metric, device_id=device_id, since=since, limit=limit)
    return {"metric": metric, "device_id": device_id, "hours": hours, "points": points}


@router.get("/forecast/{metric}")
def forecast(
    metric: str,
    device_id: str | None = None,
    history_hours: int = Query(default=24, ge=1, le=168),
    horizon_minutes: int = Query(default=30, ge=5, le=1440),
    store: Store = Depends(get_store),
) -> dict[str, Any]:
    points = store.history(
        metric=metric,
        device_id=device_id,
        since=utc_now() - timedelta(hours=history_hours),
        limit=5000,
    )
    return {
        "metric": metric,
        "device_id": device_id,
        **linear_forecast(points, horizon_minutes=horizon_minutes),
    }


@router.get("/devices/{device_id}")
def device_detail(device_id: str, store: Store = Depends(get_store)) -> dict[str, Any]:
    device = store.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="device not found")
    latest = [item for item in store.latest_readings() if item["device_id"] == device_id]
    return {"device": device, "readings": latest, "events": store.list_events(limit=50)}


@router.get("/events")
def events(
    limit: int = Query(default=100, ge=1, le=500),
    upcoming: bool | None = None,
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    return store.list_events(limit=limit, upcoming=upcoming)
