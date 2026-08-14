from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


Role = Literal["viewer", "operator", "admin"]
ReadingStatus = Literal["normal", "warning", "danger", "missing"]
Severity = Literal["info", "warning", "danger"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[\w.@+-]+$")
    password: str = Field(min_length=10, max_length=256)
    role: Role = "viewer"


class UserUpdate(BaseModel):
    role: Role | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=256)


class DeviceUpsert(BaseModel):
    id: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1, max_length=64)
    location: str = Field(default="主要魚缸", max_length=120)
    enabled: bool = True
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    settings: dict[str, Any] = Field(default_factory=dict)
    chart_config: dict[str, Any] = Field(default_factory=dict)


class DeviceKeyCreate(BaseModel):
    label: str = Field(default="default", max_length=80)


class MetricReading(BaseModel):
    metric: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    value: float | str | None = None
    unit: str = Field(default="", max_length=24)
    status: ReadingStatus = "normal"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TelemetryBatch(BaseModel):
    ts: str | int | float | None = None
    readings: list[MetricReading] = Field(min_length=1, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeviceEventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=80)
    severity: Severity = "info"
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(default="", max_length=2000)
    ts: str | int | float | None = None
    scheduled_for: str | int | float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class CommandCreate(BaseModel):
    command: str = Field(min_length=1, max_length=80)
    parameters: dict[str, Any] = Field(default_factory=dict)
    deliver_after: str | int | float | None = None
    expires_in_seconds: int = Field(default=300, ge=30, le=86400)


class CommandAck(BaseModel):
    success: bool
    result: dict[str, Any] = Field(default_factory=dict)


class ScheduleUpsert(BaseModel):
    id: int | None = None
    device_id: str = Field(min_length=3, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    command: str = Field(min_length=1, max_length=80)
    parameters: dict[str, Any] = Field(default_factory=dict)
    cron_expression: str = Field(min_length=5, max_length=120)
    timezone: str = Field(default="Asia/Taipei", max_length=80)
    enabled: bool = True
    max_runtime_seconds: int | None = Field(default=None, ge=1, le=86400)
    safety_note: str = Field(default="", max_length=500)

    @field_validator("cron_expression")
    @classmethod
    def validate_cron_shape(cls, value: str) -> str:
        if len(value.split()) != 5:
            raise ValueError("cron_expression must contain five fields")
        return value


class SettingsUpdate(BaseModel):
    retention_days: int | None = Field(default=None, ge=90, le=1825)
    dashboard_refresh_seconds: int | None = Field(default=None, ge=5, le=300)
    device_offline_seconds: int | None = Field(default=None, ge=30, le=86400)
    forecast_window_hours: int | None = Field(default=None, ge=1, le=168)
    public_dashboard: bool | None = None
    alarm_api_enabled: bool | None = None

    def provided(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class CleanupRequest(BaseModel):
    retention_days: int | None = Field(default=None, ge=90, le=1825)
    vacuum: bool = False


class AlarmCreate(BaseModel):
    alarm_type: str = Field(min_length=1, max_length=80)
    severity: Severity
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)
    payload: dict[str, Any] = Field(default_factory=dict)


class AlarmComplete(BaseModel):
    sent: bool
    result: dict[str, Any] = Field(default_factory=dict)

