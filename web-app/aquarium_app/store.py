from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import uuid
import zipfile
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import Settings
from .security import (
    hash_password,
    new_csrf_token,
    new_device_api_key,
    new_session_token,
    parse_device_api_key,
    token_hash,
    verify_password,
)


DEFAULT_SETTINGS: dict[str, Any] = {
    "retention_days": 1095,
    "dashboard_refresh_seconds": 15,
    "device_offline_seconds": 180,
    "forecast_window_hours": 24,
    "public_dashboard": True,
    "alarm_api_enabled": True,
}

DEFAULT_DEVICES = (
    ("temp-01", "水溫", "temperature", ["telemetry", "heating", "cooling"]),
    ("level-01", "水位與補水", "water_level", ["telemetry", "topoff"]),
    ("light-01", "魚缸照明", "lighting", ["telemetry", "switch", "dimming"]),
    ("feed-01", "自動餵食", "feeder", ["telemetry", "feed"]),
    ("dose-01", "滴定幫浦", "dosing", ["telemetry", "dose"]),
    ("quality-01", "水質", "water_quality", ["telemetry", "water_change"]),
    ("color-01", "水色與葉綠素", "water_color", ["telemetry"]),
    ("air-01", "曝氣與缺氧風險", "aeration", ["telemetry", "switch"]),
    ("ai-01", "TinyML 異常偵測", "anomaly", ["telemetry"]),
    ("gateway-01", "ESP-NOW / Wi-Fi 閘道", "gateway", ["telemetry", "gateway"]),
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: str | int | float | None) -> datetime:
    if value is None:
        return utc_now()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_load(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.database_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def initialize(self) -> tuple[str | None, bool]:
        self.settings.ensure_data_dir()
        schema_path = Path(__file__).with_name("schema.sql")
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(schema_path.read_text(encoding="utf-8"))
            schedule_columns = {row[1] for row in connection.execute("PRAGMA table_info(schedules)")}
            if "last_enqueued_at" not in schedule_columns:
                connection.execute("ALTER TABLE schedules ADD COLUMN last_enqueued_at TEXT")
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, ?)",
                (iso(),),
            )
        self._seed_settings()
        self._seed_devices()
        return self._ensure_admin()

    def _seed_settings(self) -> None:
        now = iso()
        with self.transaction() as connection:
            for key, value in DEFAULT_SETTINGS.items():
                connection.execute(
                    "INSERT OR IGNORE INTO app_settings(key, value_json, updated_at) VALUES(?, ?, ?)",
                    (key, json_dump(value), now),
                )

    def _seed_devices(self) -> None:
        now = iso()
        with self.transaction() as connection:
            for device_id, name, kind, capabilities in DEFAULT_DEVICES:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO devices(
                        id, name, kind, capabilities_json, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (device_id, name, kind, json_dump(capabilities), now, now),
                )

    def _ensure_admin(self) -> tuple[str | None, bool]:
        with self.connect() as connection:
            if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                return None, False
        password, generated = self.settings.bootstrap_password()
        self.create_user(self.settings.admin_user, password, "admin")
        if generated and not self.settings.testing:
            self.settings.generated_admin_path.write_text(
                f"username={self.settings.admin_user}\npassword={password}\n",
                encoding="utf-8",
            )
            try:
                os.chmod(self.settings.generated_admin_path, 0o600)
            except OSError:
                pass
        return password if generated else None, generated

    def create_user(self, username: str, password: str, role: str) -> dict[str, Any]:
        if role not in {"viewer", "operator", "admin"}:
            raise ValueError("invalid role")
        clean_username = username.strip()
        if len(clean_username) < 3:
            raise ValueError("username must contain at least 3 characters")
        now = iso()
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users(username, password_hash, role, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (clean_username, hash_password(password), role, now, now),
            )
            user_id = cursor.lastrowid
        return self.get_user(int(user_id))

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, username, role, active, created_at, updated_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, username, role, active, created_at, updated_at FROM users ORDER BY username"
            ).fetchall()
        return [dict(row) for row in rows]

    def update_user(self, user_id: int, *, role: str | None = None, active: bool | None = None) -> dict[str, Any] | None:
        if role is not None and role not in {"viewer", "operator", "admin"}:
            raise ValueError("invalid role")
        fields: list[str] = []
        values: list[Any] = []
        if role is not None:
            fields.append("role = ?")
            values.append(role)
        if active is not None:
            fields.append("active = ?")
            values.append(int(active))
        if not fields:
            return self.get_user(user_id)
        fields.append("updated_at = ?")
        values.extend([iso(), user_id])
        with self.transaction() as connection:
            connection.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
            if active is False:
                connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return self.get_user(user_id)

    def set_password(self, user_id: int, password: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (hash_password(password), iso(), user_id),
            )
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def authenticate_user(self, username: str, password: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE AND active = 1",
                (username.strip(),),
            ).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            return None
        user = dict(row)
        user.pop("password_hash", None)
        return user

    def create_session(self, user_id: int, remote_addr: str | None) -> tuple[str, str, str]:
        token = new_session_token()
        csrf = new_csrf_token()
        now = utc_now()
        expires = now + timedelta(hours=self.settings.session_hours)
        with self.transaction() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso(now),))
            connection.execute(
                """
                INSERT INTO sessions(token_hash, user_id, csrf_token, created_at, expires_at, last_seen_at, remote_addr)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (token_hash(token), user_id, csrf, iso(now), iso(expires), iso(now), remote_addr),
            )
        return token, csrf, iso(expires)

    def get_session(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        now = iso()
        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT s.csrf_token, s.expires_at, u.id, u.username, u.role, u.active
                FROM sessions s JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1
                """,
                (token_hash(token), now),
            ).fetchone()
            if row:
                connection.execute(
                    "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                    (now, token_hash(token)),
                )
        return dict(row) if row else None

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with self.transaction() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))

    def list_devices(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM devices ORDER BY created_at, id").fetchall()
        return [self._device_dict(row) for row in rows]

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
        return self._device_dict(row) if row else None

    @staticmethod
    def _device_dict(row: sqlite3.Row) -> dict[str, Any]:
        device = dict(row)
        device["enabled"] = bool(device["enabled"])
        device["capabilities"] = json_load(device.pop("capabilities_json"), [])
        device["settings"] = json_load(device.pop("settings_json"), {})
        device["chart_config"] = json_load(device.pop("chart_config_json"), {})
        return device

    def upsert_device(self, payload: dict[str, Any]) -> dict[str, Any]:
        device_id = payload["id"].strip().lower()
        now = iso()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO devices(
                    id, name, kind, location, enabled, capabilities_json,
                    settings_json, chart_config_json, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    kind = excluded.kind,
                    location = excluded.location,
                    enabled = excluded.enabled,
                    capabilities_json = excluded.capabilities_json,
                    settings_json = excluded.settings_json,
                    chart_config_json = excluded.chart_config_json,
                    updated_at = excluded.updated_at
                """,
                (
                    device_id,
                    payload["name"].strip(),
                    payload["kind"].strip(),
                    payload.get("location", "主要魚缸").strip(),
                    int(payload.get("enabled", True)),
                    json_dump(payload.get("capabilities", [])),
                    json_dump(payload.get("settings", {})),
                    json_dump(payload.get("chart_config", {})),
                    now,
                    now,
                ),
            )
        return self.get_device(device_id)

    def create_device_key(self, device_id: str, label: str) -> dict[str, str]:
        if not self.get_device(device_id):
            raise KeyError(device_id)
        api_key = new_device_api_key()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO device_api_keys(key_id, device_id, secret_hash, label, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (api_key.key_id, device_id, token_hash(api_key.secret), label.strip() or "default", iso()),
            )
        return {"key_id": api_key.key_id, "device_id": device_id, "api_key": api_key.token}

    def list_device_keys(self, device_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT key_id, device_id, label, created_at, last_used_at, revoked_at FROM device_api_keys"
        params: tuple[Any, ...] = ()
        if device_id:
            query += " WHERE device_id = ?"
            params = (device_id,)
        query += " ORDER BY created_at DESC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def revoke_device_key(self, key_id: str) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE device_api_keys SET revoked_at = COALESCE(revoked_at, ?) WHERE key_id = ?",
                (iso(), key_id),
            )
        return cursor.rowcount > 0

    def authenticate_device(self, token: str | None) -> dict[str, Any] | None:
        parsed = parse_device_api_key(token or "")
        if not parsed:
            return None
        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT k.device_id, k.secret_hash, d.enabled, d.name, d.kind
                FROM device_api_keys k JOIN devices d ON d.id = k.device_id
                WHERE k.key_id = ? AND k.revoked_at IS NULL
                """,
                (parsed.key_id,),
            ).fetchone()
            if not row or not row["enabled"] or not secrets_compare(token_hash(parsed.secret), row["secret_hash"]):
                return None
            now = iso()
            connection.execute("UPDATE device_api_keys SET last_used_at = ? WHERE key_id = ?", (now, parsed.key_id))
            connection.execute(
                "UPDATE devices SET status = 'online', last_seen_at = ?, updated_at = ? WHERE id = ?",
                (now, now, row["device_id"]),
            )
        return {"id": row["device_id"], "name": row["name"], "kind": row["kind"]}

    def ingest_readings(
        self,
        device_id: str,
        readings: Iterable[dict[str, Any]],
        recorded_at: str | int | float | None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        recorded = iso(parse_time(recorded_at))
        received = iso()
        rows = []
        for reading in readings:
            status = str(reading.get("status", "normal")).lower()
            if status not in {"normal", "warning", "danger", "missing"}:
                status = "warning"
            value = reading.get("value")
            numeric_value = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            text_value = None if numeric_value is not None or value is None else str(value)
            rows.append(
                (
                    device_id,
                    str(reading["metric"]).strip(),
                    numeric_value,
                    text_value,
                    str(reading.get("unit", "")),
                    status,
                    recorded,
                    received,
                    json_dump({**(metadata or {}), **reading.get("metadata", {})}),
                )
            )
        if not rows:
            return 0
        with self.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO sensor_readings(
                    device_id, metric, value, text_value, unit, status,
                    recorded_at, received_at, metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            connection.execute(
                "UPDATE devices SET status = 'online', last_seen_at = ?, updated_at = ? WHERE id = ?",
                (received, received, device_id),
            )
        return len(rows)

    def latest_readings(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT r.* FROM sensor_readings r
                JOIN (
                    SELECT device_id, metric, MAX(id) AS max_id
                    FROM sensor_readings GROUP BY device_id, metric
                ) latest ON latest.max_id = r.id
                ORDER BY r.device_id, r.metric
                """
            ).fetchall()
        return [self._reading_dict(row) for row in rows]

    def history(
        self,
        *,
        metric: str,
        device_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        conditions = ["metric = ?"]
        params: list[Any] = [metric]
        if device_id:
            conditions.append("device_id = ?")
            params.append(device_id)
        if since:
            conditions.append("recorded_at >= ?")
            params.append(iso(since))
        if until:
            conditions.append("recorded_at <= ?")
            params.append(iso(until))
        params.append(max(1, min(limit, 10000)))
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM sensor_readings
                WHERE {' AND '.join(conditions)}
                ORDER BY recorded_at ASC LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._reading_dict(row) for row in rows]

    @staticmethod
    def _reading_dict(row: sqlite3.Row) -> dict[str, Any]:
        reading = dict(row)
        reading["metadata"] = json_load(reading.pop("metadata_json"), {})
        return reading

    def metric_catalog(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT metric, unit, COUNT(*) AS samples,
                       MIN(recorded_at) AS first_recorded_at,
                       MAX(recorded_at) AS last_recorded_at
                FROM sensor_readings
                GROUP BY metric, unit
                ORDER BY metric
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def create_event(
        self,
        *,
        event_type: str,
        severity: str,
        title: str,
        detail: str = "",
        device_id: str | None = None,
        occurred_at: str | int | float | None = None,
        scheduled_for: str | int | float | None = None,
        source: str = "system",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if severity not in {"info", "warning", "danger"}:
            raise ValueError("invalid severity")
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO events(
                    device_id, event_type, severity, title, detail, occurred_at,
                    scheduled_for, source, payload_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    event_type,
                    severity,
                    title,
                    detail,
                    iso(parse_time(occurred_at)),
                    iso(parse_time(scheduled_for)) if scheduled_for is not None else None,
                    source,
                    json_dump(payload or {}),
                ),
            )
            event_id = int(cursor.lastrowid)
        return self.get_event(event_id)

    def get_event(self, event_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return self._event_dict(row) if row else None

    @staticmethod
    def _event_dict(row: sqlite3.Row) -> dict[str, Any]:
        event = dict(row)
        event["payload"] = json_load(event.pop("payload_json"), {})
        return event

    def list_events(self, *, limit: int = 100, upcoming: bool | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM events"
        params: list[Any] = []
        if upcoming is True:
            query += " WHERE scheduled_for IS NOT NULL AND completed_at IS NULL"
        elif upcoming is False:
            query += " WHERE scheduled_for IS NULL OR completed_at IS NOT NULL"
        query += " ORDER BY COALESCE(scheduled_for, occurred_at) DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._event_dict(row) for row in rows]

    def complete_event(self, event_id: int) -> dict[str, Any] | None:
        with self.transaction() as connection:
            connection.execute("UPDATE events SET completed_at = ? WHERE id = ?", (iso(), event_id))
        return self.get_event(event_id)

    def create_command(
        self,
        *,
        device_id: str,
        command: str,
        parameters: dict[str, Any],
        requested_by: int,
        deliver_after: str | int | float | None = None,
        expires_in_seconds: int = 300,
    ) -> dict[str, Any]:
        device = self.get_device(device_id)
        if not device or not device["enabled"]:
            raise KeyError(device_id)
        allowed = set(device["capabilities"])
        if command not in allowed and command not in {"switch", "set", "run", "stop", "sync_schedule"}:
            raise ValueError("command is not declared by this device")
        now = utc_now()
        deliver = parse_time(deliver_after) if deliver_after is not None else now
        expires = deliver + timedelta(seconds=max(30, min(expires_in_seconds, 86400)))
        command_id = uuid.uuid4().hex
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO commands(
                    id, device_id, command, parameters_json, status, requested_by,
                    requested_at, deliver_after, expires_at
                ) VALUES(?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                """,
                (
                    command_id,
                    device_id,
                    command,
                    json_dump(parameters),
                    requested_by,
                    iso(now),
                    iso(deliver),
                    iso(expires),
                ),
            )
        return self.get_command(command_id)

    def get_command(self, command_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM commands WHERE id = ?", (command_id,)).fetchone()
        return self._command_dict(row) if row else None

    @staticmethod
    def _command_dict(row: sqlite3.Row) -> dict[str, Any]:
        command = dict(row)
        command["parameters"] = json_load(command.pop("parameters_json"), {})
        command["result"] = json_load(command.pop("result_json"), None)
        return command

    def list_commands(self, *, device_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM commands"
        params: list[Any] = []
        if device_id:
            query += " WHERE device_id = ?"
            params.append(device_id)
        query += " ORDER BY requested_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._command_dict(row) for row in rows]

    def next_command(self, device_id: str) -> dict[str, Any] | None:
        now = iso()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE commands SET status = 'expired' WHERE device_id = ? AND status = 'queued' AND expires_at <= ?",
                (device_id, now),
            )
            row = connection.execute(
                """
                SELECT * FROM commands
                WHERE device_id = ? AND status = 'queued'
                  AND deliver_after <= ? AND expires_at > ?
                ORDER BY deliver_after, requested_at LIMIT 1
                """,
                (device_id, now, now),
            ).fetchone()
            if row:
                connection.execute(
                    "UPDATE commands SET status = 'delivered', delivered_at = ? WHERE id = ?",
                    (now, row["id"]),
                )
                row = connection.execute("SELECT * FROM commands WHERE id = ?", (row["id"],)).fetchone()
        return self._command_dict(row) if row else None

    def acknowledge_command(
        self,
        *,
        device_id: str,
        command_id: str,
        success: bool,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE commands SET status = ?, acknowledged_at = ?, result_json = ?
                WHERE id = ? AND device_id = ? AND status IN ('delivered', 'queued')
                """,
                ("acknowledged" if success else "failed", iso(), json_dump(result), command_id, device_id),
            )
        return self.get_command(command_id) if cursor.rowcount else None

    def cancel_command(self, command_id: str) -> dict[str, Any] | None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE commands SET status = 'cancelled' WHERE id = ? AND status = 'queued'",
                (command_id,),
            )
        return self.get_command(command_id)

    def list_schedules(self, device_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM schedules"
        params: tuple[Any, ...] = ()
        if device_id:
            query += " WHERE device_id = ?"
            params = (device_id,)
        query += " ORDER BY device_id, name"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._schedule_dict(row) for row in rows]

    @staticmethod
    def _schedule_dict(row: sqlite3.Row) -> dict[str, Any]:
        schedule = dict(row)
        schedule["enabled"] = bool(schedule["enabled"])
        schedule["parameters"] = json_load(schedule.pop("parameters_json"), {})
        return schedule

    def upsert_schedule(self, payload: dict[str, Any], user_id: int) -> dict[str, Any]:
        schedule_id = payload.get("id")
        now = iso()
        values = (
            payload["device_id"],
            payload["name"],
            payload["command"],
            json_dump(payload.get("parameters", {})),
            payload["cron_expression"],
            payload.get("timezone", "Asia/Taipei"),
            int(payload.get("enabled", True)),
            payload.get("max_runtime_seconds"),
            payload.get("safety_note", ""),
            now,
        )
        with self.transaction() as connection:
            if schedule_id:
                connection.execute(
                    """
                    UPDATE schedules SET device_id=?, name=?, command=?, parameters_json=?,
                      cron_expression=?, timezone=?, enabled=?, max_runtime_seconds=?,
                      safety_note=?, updated_at=? WHERE id=?
                    """,
                    (*values, int(schedule_id)),
                )
                result_id = int(schedule_id)
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO schedules(
                      device_id, name, command, parameters_json, cron_expression,
                      timezone, enabled, max_runtime_seconds, safety_note,
                      created_by, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*values[:-1], user_id, now, now),
                )
                result_id = int(cursor.lastrowid)
            row = connection.execute("SELECT * FROM schedules WHERE id = ?", (result_id,)).fetchone()
        return self._schedule_dict(row)

    def delete_schedule(self, schedule_id: int) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        return cursor.rowcount > 0

    def run_due_schedules(self, now: datetime | None = None) -> list[dict[str, Any]]:
        current = (now or utc_now()).astimezone(UTC)
        due: list[dict[str, Any]] = []
        for schedule in self.list_schedules():
            if not schedule["enabled"]:
                continue
            try:
                local_now = current.astimezone(ZoneInfo(schedule["timezone"]))
            except ZoneInfoNotFoundError:
                local_now = current
            minute_key = local_now.strftime("%Y-%m-%dT%H:%M")
            if schedule.get("last_enqueued_at") == minute_key:
                continue
            if not cron_matches(schedule["cron_expression"], local_now):
                continue
            params = {
                **schedule["parameters"],
                "_schedule": {
                    "id": schedule["id"],
                    "name": schedule["name"],
                    "max_runtime_seconds": schedule["max_runtime_seconds"],
                    "safety_note": schedule["safety_note"],
                },
            }
            try:
                command = self.create_command(
                    device_id=schedule["device_id"],
                    command=schedule["command"],
                    parameters=params,
                    requested_by=schedule["created_by"],
                    expires_in_seconds=600,
                )
            except (KeyError, ValueError):
                continue
            with self.transaction() as connection:
                connection.execute(
                    "UPDATE schedules SET last_enqueued_at = ?, updated_at = ? WHERE id = ?",
                    (minute_key, iso(), schedule["id"]),
                )
            due.append(command)
        return due

    def get_settings(self) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute("SELECT key, value_json FROM app_settings ORDER BY key").fetchall()
        return {row["key"]: json_load(row["value_json"], None) for row in rows}

    def update_settings(self, updates: dict[str, Any], user_id: int) -> dict[str, Any]:
        allowed = set(DEFAULT_SETTINGS)
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
        if "retention_days" in updates:
            retention = int(updates["retention_days"])
            if not 90 <= retention <= 1825:
                raise ValueError("retention_days must be between 90 and 1825")
            updates["retention_days"] = retention
        if "dashboard_refresh_seconds" in updates:
            updates["dashboard_refresh_seconds"] = max(5, min(300, int(updates["dashboard_refresh_seconds"])))
        if "device_offline_seconds" in updates:
            updates["device_offline_seconds"] = max(30, min(86400, int(updates["device_offline_seconds"])))
        if "forecast_window_hours" in updates:
            updates["forecast_window_hours"] = max(1, min(168, int(updates["forecast_window_hours"])))
        now = iso()
        with self.transaction() as connection:
            for key, value in updates.items():
                connection.execute(
                    """
                    INSERT INTO app_settings(key, value_json, updated_at, updated_by)
                    VALUES(?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                      value_json=excluded.value_json,
                      updated_at=excluded.updated_at,
                      updated_by=excluded.updated_by
                    """,
                    (key, json_dump(value), now, user_id),
                )
        return self.get_settings()

    def mark_offline_devices(self) -> int:
        settings = self.get_settings()
        threshold = utc_now() - timedelta(seconds=int(settings["device_offline_seconds"]))
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE devices SET status = 'offline', updated_at = ?
                WHERE enabled = 1 AND last_seen_at IS NOT NULL AND last_seen_at < ? AND status != 'offline'
                """,
                (iso(), iso(threshold)),
            )
        return cursor.rowcount

    def database_stats(self) -> dict[str, Any]:
        with self.connect() as connection:
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("sensor_readings", "events", "commands", "devices", "users", "alarm_outbox")
            }
            page_count = connection.execute("PRAGMA page_count").fetchone()[0]
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            freelist = connection.execute("PRAGMA freelist_count").fetchone()[0]
            range_row = connection.execute(
                "SELECT MIN(recorded_at), MAX(recorded_at) FROM sensor_readings"
            ).fetchone()
        files = [self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")]
        physical_bytes = sum(path.stat().st_size for path in files if path.exists())
        return {
            "database_path": str(self.path),
            "physical_bytes": physical_bytes,
            "physical_megabytes": round(physical_bytes / 1024 / 1024, 2),
            "allocated_bytes": page_count * page_size,
            "reclaimable_bytes": freelist * page_size,
            "counts": counts,
            "first_recorded_at": range_row[0],
            "last_recorded_at": range_row[1],
            "retention_days": self.get_settings()["retention_days"],
        }

    def cleanup(self, retention_days: int | None = None, *, vacuum: bool = False) -> dict[str, Any]:
        configured = int(self.get_settings()["retention_days"])
        days = configured if retention_days is None else int(retention_days)
        if not 90 <= days <= 1825:
            raise ValueError("retention_days must be between 90 and 1825")
        cutoff = iso(utc_now() - timedelta(days=days))
        session_cutoff = iso()
        with self.transaction() as connection:
            readings = connection.execute(
                "DELETE FROM sensor_readings WHERE recorded_at < ?", (cutoff,)
            ).rowcount
            sessions = connection.execute(
                "DELETE FROM sessions WHERE expires_at <= ?", (session_cutoff,)
            ).rowcount
            audits = connection.execute(
                "DELETE FROM audit_log WHERE created_at < ?", (cutoff,)
            ).rowcount
            alarms = connection.execute(
                "DELETE FROM alarm_outbox WHERE created_at < ? AND status IN ('sent', 'failed')",
                (cutoff,),
            ).rowcount
        if vacuum:
            with self.connect() as connection:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("VACUUM")
        return {
            "retention_days": days,
            "cutoff": cutoff,
            "deleted": {
                "sensor_readings": readings,
                "sessions": sessions,
                "audit_log": audits,
                "alarm_outbox": alarms,
            },
            "database": self.database_stats(),
        }

    def audit(
        self,
        *,
        actor_type: str,
        actor_id: str | None,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
        remote_addr: str | None = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO audit_log(
                    actor_type, actor_id, action, target_type, target_id,
                    detail_json, remote_addr, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    actor_type,
                    actor_id,
                    action,
                    target_type,
                    target_id,
                    json_dump(detail or {}),
                    remote_addr,
                    iso(),
                ),
            )

    def list_audit(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 1000)),),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["detail"] = json_load(item.pop("detail_json"), {})
            result.append(item)
        return result

    def enqueue_alarm(
        self,
        *,
        alarm_type: str,
        severity: str,
        title: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if severity not in {"info", "warning", "danger"}:
            raise ValueError("invalid severity")
        alarm_id = uuid.uuid4().hex
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO alarm_outbox(
                    id, alarm_type, severity, title, message, payload_json,
                    status, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (alarm_id, alarm_type, severity, title, message, json_dump(payload or {}), iso()),
            )
        return self.get_alarm(alarm_id)

    def get_alarm(self, alarm_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM alarm_outbox WHERE id = ?", (alarm_id,)).fetchone()
        return self._alarm_dict(row) if row else None

    @staticmethod
    def _alarm_dict(row: sqlite3.Row) -> dict[str, Any]:
        alarm = dict(row)
        alarm["payload"] = json_load(alarm.pop("payload_json"), {})
        alarm["result"] = json_load(alarm.pop("result_json"), None)
        return alarm

    def claim_alarms(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM alarm_outbox WHERE status = 'pending' ORDER BY created_at LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                connection.execute(
                    f"UPDATE alarm_outbox SET status='claimed', claimed_at=? WHERE id IN ({placeholders})",
                    (iso(), *ids),
                )
                rows = connection.execute(
                    f"SELECT * FROM alarm_outbox WHERE id IN ({placeholders}) ORDER BY created_at",
                    ids,
                ).fetchall()
        return [self._alarm_dict(row) for row in rows]

    def complete_alarm(self, alarm_id: str, *, sent: bool, result: dict[str, Any]) -> dict[str, Any] | None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE alarm_outbox SET status=?, completed_at=?, result_json=?
                WHERE id=? AND status IN ('pending', 'claimed')
                """,
                ("sent" if sent else "failed", iso(), json_dump(result), alarm_id),
            )
        return self.get_alarm(alarm_id)

    def export_zip(self) -> bytes:
        temp_backup = self.settings.data_dir / f"backup-{uuid.uuid4().hex}.sqlite3"
        try:
            with self.connect() as source:
                with closing(sqlite3.connect(temp_backup)) as target:
                    source.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    source.backup(target)
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(temp_backup, "aquarium.sqlite3")
                archive.writestr("settings.json", json.dumps(self.get_settings(), ensure_ascii=False, indent=2))
                archive.writestr("devices.json", json.dumps(self.list_devices(), ensure_ascii=False, indent=2))
                archive.writestr("readings.csv", self._readings_csv())
                archive.writestr("events.csv", self._events_csv())
            return output.getvalue()
        finally:
            temp_backup.unlink(missing_ok=True)

    def _readings_csv(self) -> str:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(
            ["id", "device_id", "metric", "value", "text_value", "unit", "status", "recorded_at", "received_at"]
        )
        with self.connect() as connection:
            cursor = connection.execute(
                """
                SELECT id, device_id, metric, value, text_value, unit, status, recorded_at, received_at
                FROM sensor_readings ORDER BY id
                """
            )
            writer.writerows(cursor)
        return buffer.getvalue()

    def _events_csv(self) -> str:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(
            ["id", "device_id", "event_type", "severity", "title", "detail", "occurred_at", "scheduled_for", "completed_at", "source"]
        )
        with self.connect() as connection:
            cursor = connection.execute(
                """
                SELECT id, device_id, event_type, severity, title, detail,
                       occurred_at, scheduled_for, completed_at, source
                FROM events ORDER BY id
                """
            )
            writer.writerows(cursor)
        return buffer.getvalue()


def secrets_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


def cron_matches(expression: str, value: datetime) -> bool:
    fields = expression.split()
    if len(fields) != 5:
        return False
    values = (value.minute, value.hour, value.day, value.month, (value.weekday() + 1) % 7)
    bounds = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
    return all(_cron_field_matches(field, current, minimum, maximum) for field, current, (minimum, maximum) in zip(fields, values, bounds))


def _cron_field_matches(field: str, current: int, minimum: int, maximum: int) -> bool:
    for part in field.split(","):
        base, _, step_text = part.partition("/")
        try:
            step = int(step_text) if step_text else 1
        except ValueError:
            return False
        if step < 1:
            return False
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            try:
                start, end = int(start_text), int(end_text)
            except ValueError:
                return False
        else:
            try:
                start = end = int(base)
            except ValueError:
                return False
        if start < minimum or end > maximum or start > end:
            return False
        if start <= current <= end and (current - start) % step == 0:
            return True
    return False
