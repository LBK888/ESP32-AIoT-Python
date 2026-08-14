from machine import Pin, freq
import network
import time

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("gateway-01")
except (ImportError, Exception):
    web = None

try:
    import web_app_config as config
except ImportError:
    config = None

LED_PIN = 2
WIFI_SSID = getattr(config, "WIFI_SSID", "YOUR_WIFI_SSID")
WIFI_PASSWORD = getattr(config, "WIFI_PASSWORD", "YOUR_WIFI_PASSWORD")

led = Pin(LED_PIN, Pin.OUT)


def blink(times=5, interval=0.25):
    for _ in range(times):
        led.value(1)
        time.sleep(interval)
        led.value(0)
        time.sleep(interval)


def connect_wifi(timeout_s=12):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    print("CPU freq:", freq())
    print("MAC:", wlan.config("mac"))
    print("Scanning Wi-Fi...")
    try:
        for ap in wlan.scan()[:8]:
            try:
                name = ap[0].decode("utf-8", "ignore")
            except Exception:
                name = str(ap[0])
            print("AP:", name, "RSSI:", ap[3])
    except Exception as exc:
        print("Wi-Fi scan failed:", type(exc).__name__)

    if WIFI_SSID.startswith("YOUR_"):
        print("Please edit WIFI_SSID and WIFI_PASSWORD first.")
        return False

    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    start = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), start) > timeout_s * 1000:
            print("Wi-Fi timeout, status =", wlan.status())
            return False
        time.sleep(0.2)
    print("Network:", wlan.ifconfig())
    return wlan


def main():
    blink()
    wlan = connect_wifi()
    ok = bool(wlan)
    print("Boot check:", "PASS" if ok else "BOARD OK, WIFI NOT READY")
    if web and ok:
        try:
            rssi = wlan.status("rssi")
        except Exception:
            rssi = None
        web.send_readings(
            [
                {"metric": "online_nodes", "value": 1, "unit": "count", "status": "normal"},
                {"metric": "wifi_rssi", "value": rssi, "unit": "dBm", "status": "normal" if rssi is not None else "missing"},
                {"metric": "mode", "value": "boot_check", "unit": "", "status": "normal"},
            ],
            {"chapter": 1, "firmware": "micropython"},
            force=True,
        )


if __name__ == "__main__":
    main()
