"""ESP32 MicroPython HTTP 整合範例。

這是獨立撰寫的參考程式，不包含課程教材或素材。實際專案請把
read_sensors() 與 execute_if_safe() 接到自己的驅動與安全規則。
"""

import gc
import time

import network
import urequests

from secrets import DASHBOARD_URL, DEVICE_API_KEY, WIFI_PASSWORD, WIFI_SSID


HEADERS = {
    "Authorization": "Bearer " + DEVICE_API_KEY,
    "Content-Type": "application/json",
}

# 裝置端只接受明確列出的命令。依實際裝置縮小此清單。
ALLOWED_COMMANDS = {"heating", "cooling", "topoff", "feed", "light", "dose", "aerate"}
MAX_RUNTIME_SECONDS = 120


def connect_wifi(timeout_seconds=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        deadline = time.ticks_add(time.ticks_ms(), timeout_seconds * 1000)
        while not wlan.isconnected():
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                raise RuntimeError("Wi-Fi connection timeout")
            time.sleep_ms(250)
    return wlan.ifconfig()


def request_json(method, path, payload=None):
    response = None
    try:
        url = DASHBOARD_URL.rstrip("/") + path
        if method == "GET":
            response = urequests.get(url, headers=HEADERS)
        else:
            response = urequests.post(url, headers=HEADERS, json=payload)
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError("HTTP {}: {}".format(response.status_code, response.text[:120]))
        return response.json()
    finally:
        if response is not None:
            response.close()
        gc.collect()


def classify_temperature(value):
    if value is None:
        return "missing"
    if value < 22.0 or value > 30.0:
        return "danger"
    if value < 24.0 or value > 28.0:
        return "warning"
    return "normal"


def read_sensors():
    """用真實 sensor driver 取代這個示範值。"""
    temperature = 26.4
    water_level = 78.0
    return temperature, water_level


def send_telemetry():
    temperature, water_level = read_sensors()
    return request_json(
        "POST",
        "/api/v1/device/telemetry",
        {
            # 讓伺服器記錄接收時間；若裝置已有可靠 UTC RTC，可改送 ISO 8601。
            "ts": None,
            "readings": [
                {
                    "metric": "water_temperature",
                    "value": temperature,
                    "unit": "°C",
                    "status": classify_temperature(temperature),
                },
                {
                    "metric": "water_level",
                    "value": water_level,
                    "unit": "%",
                    "status": "normal" if 55 <= water_level <= 90 else "warning",
                },
            ],
            "metadata": {"runtime": "micropython", "integration": "http-example"},
        },
    )


def execute_if_safe(command):
    """回傳 (success, result)。真實 actuator 必須在此保留硬體 interlock。"""
    name = command.get("command")
    parameters = command.get("parameters") or {}
    requested_runtime = int(parameters.get("runtime_seconds", 0))

    if name not in ALLOWED_COMMANDS:
        return False, {"reason": "command is not allowlisted"}
    if requested_runtime < 0 or requested_runtime > MAX_RUNTIME_SECONDS:
        return False, {"reason": "runtime exceeds local limit"}

    temperature, water_level = read_sensors()
    if name == "heating" and (temperature is None or temperature >= 28.0):
        return False, {"reason": "temperature interlock"}
    if name == "topoff" and (water_level is None or water_level >= 90.0):
        return False, {"reason": "high-water interlock"}

    # 在此呼叫繼電器／馬達 driver；完成後務必關閉輸出。
    return True, {"accepted": True, "local_safety_checked": True}


def poll_command():
    envelope = request_json("GET", "/api/v1/device/commands/next")
    command = envelope.get("command")
    if not command:
        return False

    success, result = execute_if_safe(command)
    request_json(
        "POST",
        "/api/v1/device/commands/{}/ack".format(command["id"]),
        {"success": success, "result": result},
    )
    return True


def main():
    connect_wifi()
    last_telemetry = time.ticks_add(time.ticks_ms(), -60000)
    while True:
        try:
            if time.ticks_diff(time.ticks_ms(), last_telemetry) >= 30000:
                send_telemetry()
                last_telemetry = time.ticks_ms()
            poll_command()
        except Exception as exc:
            # 生產環境請寫入受限的本機 ring buffer，避免印出 key 或完整 payload。
            print("dashboard error:", type(exc).__name__)
            time.sleep(3)
            try:
                connect_wifi()
            except Exception:
                pass
        time.sleep(5)


main()
