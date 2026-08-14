import time

try:
    import ujson as json
except ImportError:
    import json

import network
from machine import ADC, Pin
from umqtt.simple import MQTTClient

from sensor_utils import adc_summary, ntc_celsius

try:
    import web_app_config as config
except ImportError:
    config = None

WIFI_SSID = getattr(config, "WIFI_SSID", "YOUR_WIFI_SSID")
WIFI_PASSWORD = getattr(config, "WIFI_PASSWORD", "YOUR_WIFI_PASSWORD")
MQTT_HOST = getattr(config, "MQTT_HOST", "192.168.1.20")
MQTT_PORT = int(getattr(config, "MQTT_PORT", 1883))
MQTT_USERNAME = getattr(config, "MQTT_USERNAME", "")
MQTT_PASSWORD = getattr(config, "MQTT_PASSWORD", "")
DEVICE_ID = "temp-01"  # Must already exist in the Web App.
MQTT_CLIENT_ID = "aquarium-{}".format(DEVICE_ID)
TOPIC = "aquarium/{}/telemetry".format(DEVICE_ID).encode()

adc = ADC(Pin(34))  # ADC1: Wi-Fi/Bluetooth safe.
adc.atten(ADC.ATTN_11DB)
adc.width(ADC.WIDTH_12BIT)


def wifi_connect(timeout_s=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        deadline = time.ticks_add(time.ticks_ms(), timeout_s * 1000)
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), deadline) >= 0:
                raise RuntimeError("Wi-Fi failed")
            time.sleep_ms(250)
    print("Wi-Fi:", wlan.ifconfig())
    return wlan


def read_telemetry():
    stats = adc_summary(adc, 31, 5)
    temp = None if stats["rail"] or stats["std"] > 35 else ntc_celsius(stats["median"])
    status = "missing" if temp is None else "warning" if temp < 22 or temp > 29 else "normal"
    return {
        "ts": time.time() if time.localtime()[0] >= 2024 else None,
        "readings": [
            {"metric": "temp_c", "value": None if temp is None else round(temp, 2), "unit": "°C", "status": status},
            {"metric": "adc_raw", "value": round(stats["median"]), "unit": "count", "status": "missing" if stats["rail"] else "normal"},
        ],
        "metadata": {"chapter": 14, "transport": "mqtt", "adc_std": stats["std"]},
    }


def mqtt_client():
    user = MQTT_USERNAME.encode() if MQTT_USERNAME else None
    password = MQTT_PASSWORD.encode() if MQTT_PASSWORD else None
    return MQTTClient(MQTT_CLIENT_ID, MQTT_HOST, port=MQTT_PORT, user=user, password=password, keepalive=60)


def main():
    wlan = wifi_connect()
    client = mqtt_client()
    connected = False
    while True:
        try:
            if not wlan.isconnected():
                wlan = wifi_connect()
                connected = False
            if not connected:
                client.connect()
                connected = True
            payload = json.dumps(read_telemetry())
            client.publish(TOPIC, payload, qos=1)
            print("publish", payload)
        except Exception as exc:
            print("MQTT error:", type(exc).__name__)
            connected = False
            try:
                client.disconnect()
            except Exception:
                pass
            client = mqtt_client()
            time.sleep(5)
        time.sleep(30)


if __name__ == "__main__":
    main()
