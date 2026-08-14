from machine import Pin, PWM, ADC
import math
import time

from sensor_utils import adc_summary, ntc_celsius

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("gateway-01")
except (ImportError, Exception):
    web = None

TEMP_PIN = 34       # ADC1; safe with Wi-Fi/Bluetooth.
LOW_LEVEL_PIN = 32
HIGH_LEVEL_PIN = 33
LIGHT_PIN = 25
PUMP_PIN = 26
AIR_PIN = 23
LOW_ACTIVE, HIGH_ACTIVE = 0, 1
OUTPUT_ACTIVE = 1
TOP_OFF_PULSE_SECONDS = 5
TOP_OFF_COOLDOWN_SECONDS = 120

temp_adc = ADC(Pin(TEMP_PIN)); temp_adc.atten(ADC.ATTN_11DB); temp_adc.width(ADC.WIDTH_12BIT)
low_level = Pin(LOW_LEVEL_PIN, Pin.IN, Pin.PULL_UP)
high_level = Pin(HIGH_LEVEL_PIN, Pin.IN, Pin.PULL_UP)
light = PWM(Pin(LIGHT_PIN), freq=1000)
pump = Pin(PUMP_PIN, Pin.OUT, value=1 - OUTPUT_ACTIVE)
air = Pin(AIR_PIN, Pin.OUT, value=OUTPUT_ACTIVE)

state = {
    "mode": "AUTO",
    "fault": None,
    "topoff": "idle",
    "last_topoff_ticks": time.ticks_add(time.ticks_ms(), -TOP_OFF_COOLDOWN_SECONDS * 1000),
    "topoff_deadline": 0,
}


def set_output(pin, enabled):
    pin.value(OUTPUT_ACTIVE if enabled else 1 - OUTPUT_ACTIVE)


def set_pwm(value):
    value = min(1023, max(0, int(value)))
    if hasattr(light, "duty_u16"):
        light.duty_u16(int(value * 65535 / 1023))
    else:
        light.duty(value)
    return value


def stable_active(pin, active, samples=7):
    hits = 0
    for _ in range(samples):
        hits += pin.value() == active
        time.sleep_ms(20)
    return hits >= samples // 2 + 1


def read_sensors():
    stats = adc_summary(temp_adc, 31, 4)
    temp = None if stats["rail"] or stats["std"] > 35 else ntc_celsius(stats["median"])
    low = stable_active(low_level, LOW_ACTIVE)
    high = stable_active(high_level, HIGH_ACTIVE)
    rtc_valid = time.localtime()[0] >= 2024
    return {
        "temp_c": temp,
        "level_low": low,
        "level_high": high,
        "level_conflict": low and high,
        "hour": time.localtime()[3] if rtc_valid else None,
        "rtc_valid": rtc_valid,
        "adc_std": stats["std"],
    }


def risk_model(sensors):
    if sensors["temp_c"] is None or sensors["hour"] is None:
        return None
    temp_dev = abs(sensors["temp_c"] - 26) / 4
    level_risk = 1 if sensors["level_low"] else 0
    night = 1 if sensors["hour"] < 7 or sensors["hour"] >= 20 else 0
    z = min(30, max(-30, -2 + 1.1 * temp_dev + 1.5 * level_risk + 0.4 * night))
    return 1 / (1 + math.exp(-z))


def safe_outputs():
    set_output(pump, False)
    set_output(air, True)
    set_pwm(0)
    state["topoff"] = "idle"


def update_light(hour):
    if hour is None:
        return set_pwm(0)
    if 8 <= hour < 18:
        return set_pwm(700)
    if 18 <= hour < 20:
        return set_pwm(250)
    return set_pwm(0)


def update_topoff(sensors):
    now = time.ticks_ms()
    if state["topoff"] == "filling":
        if sensors["level_high"] or not sensors["level_low"] or time.ticks_diff(now, state["topoff_deadline"]) >= 0:
            set_output(pump, False)
            state["topoff"] = "idle"
            state["last_topoff_ticks"] = now
        return
    cooldown_done = time.ticks_diff(now, state["last_topoff_ticks"]) >= TOP_OFF_COOLDOWN_SECONDS * 1000
    if sensors["level_low"] and not sensors["level_high"] and cooldown_done:
        set_output(pump, True)
        state["topoff"] = "filling"
        state["topoff_deadline"] = time.ticks_add(now, TOP_OFF_PULSE_SECONDS * 1000)


def validate_sensors(sensors):
    if sensors["level_conflict"]:
        return "level_sensor_conflict"
    if sensors["temp_c"] is None:
        return "temperature_sensor_missing"
    if sensors["temp_c"] < 15 or sensors["temp_c"] > 34:
        return "temperature_out_of_safe_range"
    return None


def main():
    safe_outputs()
    last_fault = None
    while True:
        sensors = read_sensors()
        risk = risk_model(sensors)
        state["fault"] = validate_sensors(sensors)
        if state["fault"]:
            safe_outputs()
            brightness = 0
        else:
            brightness = update_light(sensors["hour"])
            update_topoff(sensors)
            set_output(air, risk is None or risk > 0.45 or sensors["temp_c"] > 28)
        print("state={}, sensors={}, risk={}".format(state, sensors, risk))
        if web:
            temp_status = "missing" if sensors["temp_c"] is None else "warning" if sensors["temp_c"] < 22 or sensors["temp_c"] > 29 else "normal"
            level_status = "danger" if sensors["level_conflict"] else "warning" if sensors["level_low"] or sensors["level_high"] else "normal"
            web.send_readings([
                {"metric": "temp_c", "value": None if sensors["temp_c"] is None else round(sensors["temp_c"], 2), "unit": "°C", "status": temp_status},
                {"metric": "level_low", "value": int(sensors["level_low"]), "unit": "bool", "status": level_status},
                {"metric": "brightness_pct", "value": round(brightness * 100 / 1023, 1), "unit": "%", "status": "normal"},
                {"metric": "oxygen_risk", "value": None if risk is None else round(risk * 100, 1), "unit": "%", "status": "missing" if risk is None else "normal"},
                {"metric": "mode", "value": state["mode"], "unit": "", "status": "danger" if state["fault"] else "normal"},
            ], {"chapter": 16, "fault": state["fault"], "topoff": state["topoff"]})
            if state["fault"] and state["fault"] != last_fault:
                web.send_event("controller.fault", "danger", "Integrated controller entered safe state", state["fault"], sensors)
        last_fault = state["fault"]
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    finally:
        safe_outputs()
