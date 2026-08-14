"""Small, optional, fail-open HTTP adapter for the aquarium Web App.

Hardware control never depends on this module.  Import it in a chapter inside a
try/except block; deleting this file or leaving WEB_APP_ENABLED=False therefore
does not change the local sensor/control behavior.
"""

import gc
import time

try:
    import ujson as json
except ImportError:  # CPython syntax/tests
    import json

try:
    import web_app_config as config
except ImportError:
    config = None


VALID_STATUSES = ("normal", "warning", "danger", "missing")
_wlan = None


def _ticks_due(now, deadline):
    return time.ticks_diff(now, deadline) >= 0


def _timestamp_or_none():
    try:
        return time.time() if time.localtime()[0] >= 2024 else None
    except Exception:
        return None


def _base_url():
    explicit = getattr(config, "WEB_APP_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    scheme = getattr(config, "WEB_APP_SCHEME", "http")
    host = getattr(config, "WEB_APP_HOST", "127.0.0.1")
    port = int(getattr(config, "WEB_APP_PORT", 8000))
    return "{}://{}:{}".format(scheme, host, port)


def _wifi_connected():
    global _wlan
    if _wlan is not None and _wlan.isconnected():
        return True
    import network

    _wlan = network.WLAN(network.STA_IF)
    _wlan.active(True)
    ssid = getattr(config, "WIFI_SSID", "")
    password = getattr(config, "WIFI_PASSWORD", "")
    if not ssid or ssid.startswith("YOUR_"):
        raise RuntimeError("web_app_config.py Wi-Fi settings are incomplete")
    _wlan.connect(ssid, password)
    timeout_s = int(getattr(config, "WEB_APP_WIFI_TIMEOUT_SECONDS", 15))
    deadline = time.ticks_add(time.ticks_ms(), timeout_s * 1000)
    while not _wlan.isconnected():
        if _ticks_due(time.ticks_ms(), deadline):
            raise RuntimeError("Wi-Fi connection timeout")
        time.sleep_ms(250)
    return True


class WebAppClient:
    def __init__(self, device_id):
        keys = getattr(config, "DEVICE_API_KEYS", {}) if config else {}
        self.device_id = device_id
        self.api_key = keys.get(device_id, "")
        self.enabled = bool(
            config
            and getattr(config, "WEB_APP_ENABLED", False)
            and self.api_key
            and "REPLACE" not in self.api_key
        )
        self.queue = []
        self.last_telemetry = time.ticks_add(time.ticks_ms(), -60000)
        self.last_command = time.ticks_add(time.ticks_ms(), -60000)
        self.retry_after = 0
        self.failures = 0

    def _request(self, method, path, payload=None):
        _wifi_connected()
        import urequests

        response = None
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }
        try:
            url = _base_url() + path
            if method == "GET":
                response = urequests.get(url, headers=headers)
            else:
                body = json.dumps(payload)
                response = urequests.post(url, headers=headers, data=body)
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError("Web App HTTP {}".format(response.status_code))
            return response.json()
        finally:
            if response is not None:
                response.close()
            gc.collect()

    def _can_try(self):
        return self.enabled and _ticks_due(time.ticks_ms(), self.retry_after)

    def _record_failure(self, exc):
        self.failures += 1
        backoff_s = min(60, 2 ** min(self.failures, 5))
        self.retry_after = time.ticks_add(time.ticks_ms(), backoff_s * 1000)
        print("Web App unavailable (local control continues):", type(exc).__name__)

    def _record_success(self):
        self.failures = 0
        self.retry_after = 0

    def _enqueue(self, payload):
        limit = int(getattr(config, "WEB_APP_QUEUE_SIZE", 12))
        self.queue.append(payload)
        if len(self.queue) > limit:
            self.queue.pop(0)

    def send_readings(self, readings, metadata=None, force=False):
        """Send a batch or retain a bounded in-memory queue during outages."""
        if not self.enabled:
            return False
        now = time.ticks_ms()
        interval = int(getattr(config, "WEB_APP_TELEMETRY_SECONDS", 15)) * 1000
        if not force and time.ticks_diff(now, self.last_telemetry) < interval:
            return False
        self.last_telemetry = now
        cleaned = []
        for item in readings:
            row = dict(item)
            if row.get("status") not in VALID_STATUSES:
                row["status"] = "warning"
            if row.get("value") is None:
                row["status"] = "missing"
            cleaned.append(row)
        payload = {
            "ts": _timestamp_or_none(),
            "readings": cleaned,
            "metadata": metadata or {},
        }
        self._enqueue(payload)
        if not self._can_try():
            return False
        try:
            while self.queue:
                self._request("POST", "/api/v1/device/telemetry", self.queue[0])
                self.queue.pop(0)
            self._record_success()
            return True
        except Exception as exc:
            self._record_failure(exc)
            return False

    def send_event(self, event_type, severity, title, detail="", payload=None):
        if not self._can_try():
            return False
        try:
            self._request(
                "POST",
                "/api/v1/device/events",
                {
                    "event_type": event_type,
                    "severity": severity,
                    "title": title,
                    "detail": detail,
                    "ts": _timestamp_or_none(),
                    "payload": payload or {},
                },
            )
            self._record_success()
            return True
        except Exception as exc:
            self._record_failure(exc)
            return False

    def poll_command(self, handler):
        """Run one allow-listed command through the chapter's local handler."""
        if not self._can_try():
            return False
        now = time.ticks_ms()
        interval = int(getattr(config, "WEB_APP_COMMAND_SECONDS", 5)) * 1000
        if time.ticks_diff(now, self.last_command) < interval:
            return False
        self.last_command = now
        try:
            envelope = self._request("GET", "/api/v1/device/commands/next")
            command = envelope.get("command")
            if not command:
                self._record_success()
                return False
            try:
                success, result = handler(command)
            except Exception as exc:
                success = False
                result = {"reason": "local handler error", "error": type(exc).__name__}
            self._request(
                "POST",
                "/api/v1/device/commands/{}/ack".format(command["id"]),
                {"success": bool(success), "result": result or {}},
            )
            self._record_success()
            return True
        except Exception as exc:
            self._record_failure(exc)
            return False


def get_web_client(device_id):
    return WebAppClient(device_id)

