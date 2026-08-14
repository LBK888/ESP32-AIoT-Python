from machine import Pin, PWM
import time

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("level-01")
except (ImportError, Exception):
    web = None

# XKC-Y25-V primary water-level safety monitor.
# Measure OUT with a multimeter first. If OUT can be 5-24 V, do not connect
# it directly to ESP32; use a divider, optocoupler, or level shifter.

LOW_LEVEL_PIN = 32      # safer than original boot-strapping GPIO15
HIGH_LEVEL_PIN = 33     # safer than boot-strapping GPIO4
BUZZER_PIN = 25         # safer than boot-strapping GPIO2

LOW_ACTIVE = 0          # set to 0 or 1 after checking MODE/OUT logic
HIGH_ACTIVE = 1         # set to 0 or 1 after checking MODE/OUT logic
USE_HIGH_SENSOR = True

low_sensor = Pin(LOW_LEVEL_PIN, Pin.IN, Pin.PULL_UP)
high_sensor = Pin(HIGH_LEVEL_PIN, Pin.IN, Pin.PULL_UP)
buzzer = PWM(Pin(BUZZER_PIN, Pin.OUT), freq=1, duty=0)


def stable_active(pin, active_value, samples=7, interval_ms=60):
    hits = 0
    for _ in range(samples):
        if pin.value() == active_value:
            hits += 1
        time.sleep_ms(interval_ms)
    return hits >= (samples // 2 + 1)


def beep(freqs, duration_ms=180, gap_ms=120):
    for freq in freqs:
        buzzer.freq(freq)
        if hasattr(buzzer, "duty_u16"):
            buzzer.duty_u16(20000)
        else:
            buzzer.duty(512)
        time.sleep_ms(duration_ms)
        if hasattr(buzzer, "duty_u16"):
            buzzer.duty_u16(0)
        else:
            buzzer.duty(0)
        time.sleep_ms(gap_ms)


def read_level_state():
    low_alarm = stable_active(low_sensor, LOW_ACTIVE)
    high_alarm = False
    if USE_HIGH_SENSOR:
        high_alarm = stable_active(high_sensor, HIGH_ACTIVE)
    if low_alarm and high_alarm:
        return "SENSOR_CONFLICT"
    if high_alarm:
        return "HIGH_LEVEL"
    if low_alarm:
        return "LOW_LEVEL"
    return "NORMAL"


def main():
    last_state = None
    while True:
        state = read_level_state()
        print("water_level_state =", state)
        if state != last_state:
            if state == "LOW_LEVEL":
                print("Warning: water level is too low.")
                beep([349, 349, 349])
            elif state == "HIGH_LEVEL":
                print("Warning: water level is too high. Stop top-off.")
                beep([523])
            elif state == "SENSOR_CONFLICT":
                print("Warning: impossible XKC combination; check wiring/installation.")
                beep([392, 294, 392, 294])
        status = "normal" if state == "NORMAL" else "danger" if state == "SENSOR_CONFLICT" else "warning"
        if web:
            web.send_readings([
                {"metric": "level_low", "value": 1 if state == "LOW_LEVEL" else 0, "unit": "bool", "status": status},
                {"metric": "level_state", "value": state.lower(), "unit": "", "status": status},
            ], {"chapter": 6, "dual_xkc": USE_HIGH_SENSOR})
            if state != last_state and state != "NORMAL":
                web.send_event("water_level." + state.lower(), "danger" if state == "SENSOR_CONFLICT" else "warning", "Water-level warning", state)
        last_state = state
        time.sleep(1)


if __name__ == "__main__":
    main()
