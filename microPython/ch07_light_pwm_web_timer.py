from machine import Pin, PWM
import network
import socket
import time

try:  # Optional: remove these four lines to remove central Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("light-01")
except (ImportError, Exception):
    web = None

try:
    import web_app_config as config
except ImportError:
    config = None

WIFI_SSID = getattr(config, "WIFI_SSID", "YOUR_WIFI_SSID")
WIFI_PASSWORD = getattr(config, "WIFI_PASSWORD", "YOUR_WIFI_PASSWORD")
LED_PWM_PIN = 25
PWM_FREQ = 1000
UTC_OFFSET_HOURS = 8

pwm = PWM(Pin(LED_PWM_PIN), freq=PWM_FREQ)
mode = "auto"
manual_duty = 0


def set_duty(value_0_1023):
    value = min(1023, max(0, int(value_0_1023)))
    if hasattr(pwm, "duty_u16"):
        pwm.duty_u16(int(value * 65535 / 1023))
    else:
        pwm.duty(value)
    return value


def local_hour():
    if time.localtime()[0] < 2024:
        return None
    return ((time.time() + UTC_OFFSET_HOURS * 3600) % 86400) / 3600


def auto_duty():
    hour = local_hour()
    if hour is None:  # Unknown clock must not create unlimited light exposure.
        return 0
    if 8 <= hour < 10:
        return int((hour - 8) / 2 * 800)
    if 10 <= hour < 18:
        return 800
    if 18 <= hour < 20:
        return int((20 - hour) / 2 * 800)
    return 0


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        deadline = time.ticks_add(time.ticks_ms(), 30000)
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), deadline) >= 0:
                raise RuntimeError("Wi-Fi connect timeout")
            time.sleep_ms(250)
    try:
        import ntptime
        ntptime.settime()
    except Exception as exc:
        print("NTP unavailable; auto mode stays off until RTC is valid:", type(exc).__name__)
    print("IP:", wlan.ifconfig()[0])
    return wlan.ifconfig()[0]


def parse_request(req):
    global mode, manual_duty
    request_line = req.split("\r\n", 1)[0]
    if request_line == "GET /on HTTP/1.1" or request_line.startswith("GET /on HTTP/"):
        mode, manual_duty = "manual", 900
    elif request_line.startswith("GET /off HTTP/"):
        mode, manual_duty = "manual", 0
    elif request_line.startswith("GET /auto HTTP/"):
        mode = "auto"
    elif request_line.startswith("GET /brightness?duty="):
        value = request_line.split("duty=", 1)[1].split(" ", 1)[0]
        manual_duty = min(1023, max(0, int(value)))
        mode = "manual"


def handle_web_command(command):
    global mode, manual_duty
    name = command.get("command")
    parameters = command.get("parameters") or {}
    if name == "switch":
        mode = "manual"
        manual_duty = 900 if bool(parameters.get("enabled", False)) else 0
    elif name == "dimming":
        pct = min(100.0, max(0.0, float(parameters.get("brightness_pct", 0))))
        mode, manual_duty = "manual", int(pct * 1023 / 100)
    else:
        return False, {"reason": "command is not allow-listed in chapter 7"}
    return True, {"mode": mode, "brightness_pct": round(manual_duty * 100 / 1023, 1), "local_safety_checked": True}


def main():
    connect_wifi()
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", 80))
    server.listen(2)
    server.settimeout(0.2)
    while True:
        client = None
        try:
            client, addr = server.accept()
            req = client.recv(1024).decode("utf-8", "ignore")
            parse_request(req)
            duty = auto_duty() if mode == "auto" else manual_duty
            body = "mode={}, duty={}\n/on /off /auto /brightness?duty=0..1023".format(mode, duty)
            client.send(("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n" + body).encode())
        except OSError:
            pass
        except (ValueError, IndexError) as exc:
            print("Bad HTTP request:", type(exc).__name__)
        finally:
            if client:
                client.close()
        duty = set_duty(auto_duty() if mode == "auto" else manual_duty)
        if web:
            web.send_readings([
                {"metric": "brightness_pct", "value": round(duty * 100 / 1023, 1), "unit": "%", "status": "normal"},
                {"metric": "mode", "value": mode, "unit": "", "status": "normal"},
            ], {"chapter": 7, "rtc_valid": local_hour() is not None})
            web.poll_command(handle_web_command)
        time.sleep_ms(100)


if __name__ == "__main__":
    main()
