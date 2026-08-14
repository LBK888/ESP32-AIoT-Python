from machine import Pin
import time

from sensor_utils import median

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("level-01")
except (ImportError, Exception):
    web = None

# GPIO15 in the original worksheet is a boot-strapping pin. GPIO32/33 are safer
# defaults and remain usable while Wi-Fi/Bluetooth are active.
LOW_SENSOR_PIN = 32
HIGH_SENSOR_PIN = 33
PUMP_PIN = 26
LOW_ACTIVE = 0
HIGH_ACTIVE = 1
USE_HIGH_SENSOR = True
PUMP_ACTIVE = 1
DEBOUNCE_SAMPLES = 7
MAX_FILL_SECONDS = 20
COOLDOWN_SECONDS = 60

low_sensor = Pin(LOW_SENSOR_PIN, Pin.IN, Pin.PULL_UP)
high_sensor = Pin(HIGH_SENSOR_PIN, Pin.IN, Pin.PULL_UP) if USE_HIGH_SENSOR else None
pump = Pin(PUMP_PIN, Pin.OUT, value=1 - PUMP_ACTIVE)
successful_fill_seconds = []
last_fill_finished = time.ticks_add(time.ticks_ms(), -COOLDOWN_SECONDS * 1000)


def stable_active(pin, active_value, samples=DEBOUNCE_SAMPLES):
    hits = 0
    for _ in range(samples):
        hits += 1 if pin.value() == active_value else 0
        time.sleep_ms(60)
    return hits >= samples // 2 + 1


def level_state():
    low = stable_active(low_sensor, LOW_ACTIVE)
    high = stable_active(high_sensor, HIGH_ACTIVE) if high_sensor else False
    if low and high:
        return "SENSOR_CONFLICT"
    if high:
        return "HIGH_LEVEL"
    if low:
        return "LOW_LEVEL"
    return "NORMAL"


def pump_on(enabled):
    pump.value(PUMP_ACTIVE if enabled else 1 - PUMP_ACTIVE)


def adaptive_limit():
    if len(successful_fill_seconds) < 3:
        return MAX_FILL_SECONDS
    typical = median(successful_fill_seconds)
    return min(MAX_FILL_SECONDS, max(5, typical * 2.5))


def fill_once(requested_limit=None):
    """Return (success, seconds, reason); every exit path turns the pump off."""
    state = level_state()
    if state != "LOW_LEVEL":
        return False, 0.0, "level is not safely low: " + state
    limit = adaptive_limit()
    if requested_limit is not None:
        limit = min(limit, max(1, int(requested_limit)))
    started = time.ticks_ms()
    reason = "unknown"
    success = False
    try:
        pump_on(True)
        while True:
            state = level_state()
            elapsed = time.ticks_diff(time.ticks_ms(), started) / 1000
            if state in ("NORMAL", "HIGH_LEVEL"):
                success, reason = True, "target reached"
                break
            if state == "SENSOR_CONFLICT":
                reason = "sensor conflict"
                break
            if elapsed >= limit:
                reason = "fill timeout; check source tank, hose, and sensor"
                break
            time.sleep_ms(250)
    finally:
        pump_on(False)
    duration = time.ticks_diff(time.ticks_ms(), started) / 1000
    if success:
        successful_fill_seconds.append(duration)
        del successful_fill_seconds[:-10]
    return success, duration, reason


def handle_web_command(command):
    if command.get("command") != "topoff":
        return False, {"reason": "command is not allow-listed in chapter 5"}
    parameters = command.get("parameters") or {}
    success, seconds, reason = fill_once(parameters.get("runtime_seconds", MAX_FILL_SECONDS))
    return success, {"duration_seconds": seconds, "reason": reason, "local_safety_checked": True}


def main():
    global last_fill_finished
    pump_on(False)
    while True:
        state = level_state()
        status = "normal" if state == "NORMAL" else "danger" if state == "SENSOR_CONFLICT" else "warning"
        print("water_level_state =", state)
        cooldown_done = time.ticks_diff(time.ticks_ms(), last_fill_finished) >= COOLDOWN_SECONDS * 1000
        if state == "LOW_LEVEL" and cooldown_done:
            success, seconds, reason = fill_once()
            last_fill_finished = time.ticks_ms()
            print("Top-off stopped:", success, seconds, reason)
            if web:
                web.send_event(
                    "topoff.completed" if success else "topoff.blocked",
                    "info" if success else "danger",
                    "Top-off completed" if success else "Top-off stopped by local safety",
                    reason,
                    {"duration_seconds": seconds},
                )
        else:
            pump_on(False)
        if web:
            web.send_readings([
                {"metric": "level_low", "value": 1 if state == "LOW_LEVEL" else 0, "unit": "bool", "status": status},
                {"metric": "level_state", "value": state.lower(), "unit": "", "status": status},
            ], {"chapter": 5, "pump_on": False})
            web.poll_command(handle_web_command)
        time.sleep(2)


if __name__ == "__main__":
    main()
