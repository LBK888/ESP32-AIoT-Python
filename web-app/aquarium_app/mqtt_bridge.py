from __future__ import annotations

import json
import logging
from typing import Any

from .config import Settings
from .store import Store


logger = logging.getLogger(__name__)


UNITS = {
    "temp_c": "°C",
    "temp_demo_c": "°C",
    "level_pct": "%",
    "ph": "pH",
    "ec_us_cm": "µS/cm",
    "turbidity_ntu": "NTU",
    "do_mg_l": "mg/L",
    "oxygen_risk": "%",
    "brightness_pct": "%",
    "anomaly_score": "%",
}


class MqttBridge:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self.client: Any = None

    def start(self) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError("MQTT is enabled but the mqtt optional dependency is not installed") from exc
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="aquarium-dashboard")
        if self.settings.mqtt_username:
            self.client.username_pw_set(self.settings.mqtt_username, self.settings.mqtt_password)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=60)
        self.client.loop_start()

    def stop(self) -> None:
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        if int(reason_code) == 0:
            client.subscribe("aquarium/+/telemetry", qos=1)
            client.subscribe("aquarium/+/event", qos=1)
            logger.info("MQTT bridge connected to %s:%s", self.settings.mqtt_host, self.settings.mqtt_port)
        else:
            logger.error("MQTT connection failed: %s", reason_code)

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        try:
            parts = message.topic.split("/")
            if len(parts) != 3 or parts[0] != "aquarium":
                return
            device_id, message_type = parts[1], parts[2]
            payload = json.loads(message.payload.decode("utf-8"))
            if not self.store.get_device(device_id):
                logger.warning("Ignoring MQTT payload from unknown device %s", device_id)
                return
            if message_type == "telemetry":
                self._ingest_telemetry(device_id, payload)
            elif message_type == "event":
                self.store.create_event(
                    device_id=device_id,
                    event_type=str(payload.get("event_type", "mqtt.event")),
                    severity=_severity(payload.get("severity", payload.get("status", "info"))),
                    title=str(payload.get("title", "MQTT event")),
                    detail=str(payload.get("detail", "")),
                    occurred_at=payload.get("ts"),
                    source="mqtt",
                    payload=payload,
                )
        except Exception:
            logger.exception("Unable to process MQTT message on %s", message.topic)

    def _ingest_telemetry(self, device_id: str, payload: dict[str, Any]) -> None:
        shared_status = _reading_status(payload.get("status", "normal"))
        if isinstance(payload.get("readings"), list):
            readings = payload["readings"]
        else:
            readings = [
                {
                    "metric": key,
                    "value": value,
                    "unit": UNITS.get(key, ""),
                    "status": shared_status,
                }
                for key, value in payload.items()
                if key not in {"ts", "status", "device_id"} and isinstance(value, (int, float, str))
            ]
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        self.store.ingest_readings(device_id, readings, payload.get("ts"), {**metadata, "transport": "mqtt"})


def _reading_status(value: Any) -> str:
    normalized = str(value).lower()
    return {
        "ok": "normal",
        "normal": "normal",
        "warn": "warning",
        "warning": "warning",
        "alert": "danger",
        "danger": "danger",
        "offline": "missing",
        "missing": "missing",
    }.get(normalized, "warning")


def _severity(value: Any) -> str:
    normalized = str(value).lower()
    return {"ok": "info", "normal": "info", "warn": "warning", "alert": "danger"}.get(
        normalized,
        normalized if normalized in {"info", "warning", "danger"} else "warning",
    )
