from machine import Pin, ADC
import time

from sensor_utils import adc_summary

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("quality-01")
except (ImportError, Exception):
    web = None

PH_PIN, EC_PIN, TURB_PIN = 32, 33, 35  # all ADC1
LOW_LEVEL_PIN, HIGH_LEVEL_PIN = 16, 17
DRAIN_PIN, FILL_PIN = 18, 19
LOW_ACTIVE, HIGH_ACTIVE = 0, 1
PUMP_ACTIVE = 1
MAX_DRAIN_SECONDS = 20
MAX_FILL_SECONDS = 20
MIN_INTERVAL_HOURS = 24
AUTO_WATER_CHANGE_ENABLED = False  # Enable only after calibration + dry-run.
CALIBRATION_VERIFIED = False

ph_adc = ADC(Pin(PH_PIN)); ph_adc.atten(ADC.ATTN_11DB); ph_adc.width(ADC.WIDTH_12BIT)
ec_adc = ADC(Pin(EC_PIN)); ec_adc.atten(ADC.ATTN_11DB); ec_adc.width(ADC.WIDTH_12BIT)
turb_adc = ADC(Pin(TURB_PIN)); turb_adc.atten(ADC.ATTN_11DB); turb_adc.width(ADC.WIDTH_12BIT)
low_level = Pin(LOW_LEVEL_PIN, Pin.IN, Pin.PULL_UP)
high_level = Pin(HIGH_LEVEL_PIN, Pin.IN, Pin.PULL_UP)
drain = Pin(DRAIN_PIN, Pin.OUT, value=1 - PUMP_ACTIVE)
fill = Pin(FILL_PIN, Pin.OUT, value=1 - PUMP_ACTIVE)
last_change_ticks = time.ticks_add(time.ticks_ms(), -MIN_INTERVAL_HOURS * 3600000)


def pump_on(pin, enabled):
    pin.value(PUMP_ACTIVE if enabled else 1 - PUMP_ACTIVE)


def all_pumps_off():
    pump_on(drain, False)
    pump_on(fill, False)


def stable_active(pin, active_value, samples=7):
    hits = 0
    for _ in range(samples):
        hits += pin.value() == active_value
        time.sleep_ms(50)
    return hits >= samples // 2 + 1


def level_state():
    low = stable_active(low_level, LOW_ACTIVE)
    high = stable_active(high_level, HIGH_ACTIVE)
    if low and high:
        return "conflict"
    if low:
        return "low"
    if high:
        return "high"
    return "normal"


def voltage_summary(adc):
    stats = adc_summary(adc, 31, 4)
    return stats["median"] * 3.3 / 4095, stats


def read_quality():
    ph_v, ph_s = voltage_summary(ph_adc)
    ec_v, ec_s = voltage_summary(ec_adc)
    turb_v, turb_s = voltage_summary(turb_adc)
    if any(s["rail"] or s["std"] > 45 for s in (ph_s, ec_s, turb_s)):
        return None
    ph = -5.70 * ph_v + 21.34       # Replace using pH 4/7/10 calibration.
    ec = 1000.0 * ec_v              # Replace using EC standard solution.
    turb = max(0, -300.0 * turb_v + 1000)
    if not (0 <= ph <= 14 and 0 <= ec <= 10000 and 0 <= turb <= 4000):
        return None
    return ph, ec, turb


def quality_score(ph, ec, turb):
    # Explicit, bounded rule score; not a universal biological index.
    score = 100.0
    score -= min(40.0, abs(ph - 7.2) * 12.0)
    score -= min(30.0, max(0.0, ec - 900.0) / 20.0)
    score -= min(30.0, turb / 20.0)
    return max(0.0, score)


def run_until(pin, stop_state, timeout_s):
    started = time.ticks_ms()
    try:
        pump_on(pin, True)
        while time.ticks_diff(time.ticks_ms(), started) < timeout_s * 1000:
            state = level_state()
            if state == "conflict":
                return False, "level sensor conflict"
            if state == stop_state:
                return True, "target level reached"
            time.sleep_ms(250)
        return False, "level target timeout"
    finally:
        pump_on(pin, False)


def run_water_change():
    global last_change_ticks
    if not AUTO_WATER_CHANGE_ENABLED or not CALIBRATION_VERIFIED:
        return False, "auto change disabled until calibration and dry-run are verified"
    if level_state() != "normal":
        return False, "initial water level is not normal"
    all_pumps_off()
    try:
        ok, reason = run_until(drain, "low", MAX_DRAIN_SECONDS)
        if not ok:
            return False, "drain: " + reason
        time.sleep(2)
        ok, reason = run_until(fill, "high", MAX_FILL_SECONDS)
        if not ok:
            return False, "fill: " + reason
        last_change_ticks = time.ticks_ms()
        return True, "completed"
    finally:
        all_pumps_off()


def handle_web_command(command):
    if command.get("command") != "water_change":
        return False, {"reason": "command is not allow-listed in chapter 11"}
    success, reason = run_water_change()
    return success, {"reason": reason, "local_safety_checked": True}


def main():
    all_pumps_off()
    while True:
        readings = read_quality()
        if readings is None:
            ph = ec = turb = score = None
            status = "missing"
            print("Water-quality input missing/unstable; automatic change blocked")
        else:
            ph, ec, turb = readings
            score = quality_score(ph, ec, turb)
            status = "danger" if score < 55 else "warning" if score < 75 else "normal"
            print("pH={:.2f}, EC={:.0f}, turb={:.1f}, score={:.1f}".format(ph, ec, turb, score))
            interval_ok = time.ticks_diff(time.ticks_ms(), last_change_ticks) >= MIN_INTERVAL_HOURS * 3600000
            if score < 55 and interval_ok:
                success, reason = run_water_change()
                print("water change:", success, reason)
                if web:
                    web.send_event("water_change.completed" if success else "water_change.blocked", "info" if success else "danger", "Water-change result", reason)
        if web:
            web.send_readings([
                {"metric": "ph", "value": None if ph is None else round(ph, 2), "unit": "pH", "status": status},
                {"metric": "ec_us_cm", "value": None if ec is None else round(ec), "unit": "µS/cm", "status": status},
                {"metric": "turbidity_ntu", "value": None if turb is None else round(turb, 1), "unit": "NTU", "status": status},
                {"metric": "water_quality_score", "value": None if score is None else round(score, 1), "unit": "%", "status": status},
            ], {"chapter": 11, "calibration_verified": CALIBRATION_VERIFIED, "level_state": level_state()})
            web.poll_command(handle_web_command)
        time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    finally:
        all_pumps_off()
