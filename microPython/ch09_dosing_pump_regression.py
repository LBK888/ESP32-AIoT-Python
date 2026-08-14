from machine import Pin
import time

try:
    import ujson as json
except ImportError:
    import json

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("dose-01")
except (ImportError, Exception):
    web = None

PUMP_PIN = 27
PUMP_ACTIVE = 1
DAILY_DOSE_ML = 2.0
MAX_DAILY_ML = 5.0
MAX_SINGLE_ML = 2.5
MAX_RUNTIME_SECONDS = 30
MIN_DOSE_GAP_SECONDS = 4 * 60 * 60
STATE_FILE = "dose_state.json"
CALIBRATION = [(5, 1.2), (10, 2.6), (20, 5.1)]

pump = Pin(PUMP_PIN, Pin.OUT, value=1 - PUMP_ACTIVE)
today_dosed = 0.0
last_day = None
last_dose_ticks = time.ticks_add(time.ticks_ms(), -MIN_DOSE_GAP_SECONDS * 1000)
last_dose_epoch = 0
state_ready = False


def pump_on(enabled):
    pump.value(PUMP_ACTIVE if enabled else 1 - PUMP_ACTIVE)


def linear_fit(points):
    if len(points) < 3 or len(set(p[0] for p in points)) < 2:
        raise ValueError("Need at least three calibration points at two runtimes")
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    xb, yb = sum(xs) / len(xs), sum(ys) / len(ys)
    denom = sum((x - xb) ** 2 for x in xs)
    slope = sum((x - xb) * (y - yb) for x, y in zip(xs, ys)) / denom
    intercept = yb - slope * xb
    fitted = [slope * x + intercept for x in xs]
    total = sum((y - yb) ** 2 for y in ys)
    residual = sum((y - fit) ** 2 for y, fit in zip(ys, fitted))
    r2 = 1.0 if total == 0 else 1.0 - residual / total
    if slope <= 0 or r2 < 0.95:
        raise ValueError("Pump calibration is non-linear or inconsistent")
    return slope, intercept, r2


ML_PER_SEC, INTERCEPT, CALIBRATION_R2 = linear_fit(CALIBRATION)


def seconds_for_ml(ml):
    seconds = (float(ml) - INTERCEPT) / ML_PER_SEC
    if seconds <= 0 or seconds > MAX_RUNTIME_SECONDS:
        raise ValueError("Requested dose is outside calibrated/safe runtime")
    return seconds


def rtc_valid():
    return time.localtime()[0] >= 2024


def save_state():
    # Reserve/account the dose before energizing the pump.  A reset can then
    # under-dose, but cannot silently repeat an additive dose.
    with open(STATE_FILE + ".tmp", "w") as stream:
        json.dump({"day": last_day, "today_dosed": today_dosed, "last_dose_epoch": last_dose_epoch}, stream)
    try:
        import os
        try:
            os.remove(STATE_FILE)
        except OSError:
            pass
        os.rename(STATE_FILE + ".tmp", STATE_FILE)
    except Exception:
        raise RuntimeError("Unable to persist dose safety ledger")


def load_state():
    global today_dosed, last_day, last_dose_epoch, state_ready
    if not rtc_valid():
        return False
    current_day = list(time.localtime()[:3])
    saved = None
    try:
        # Prefer the temporary file: it is the newer, already reserved ledger
        # if power failed between writing it and completing rename().
        for candidate in (STATE_FILE + ".tmp", STATE_FILE):
            try:
                with open(candidate, "r") as stream:
                    saved = json.load(stream)
                break
            except OSError:
                pass
        if saved is None:
            raise OSError("dose ledger not found")
        saved_day = saved.get("day")
        today_dosed = float(saved.get("today_dosed", 0)) if saved_day == current_day else 0.0
        last_dose_epoch = int(saved.get("last_dose_epoch", 0))
    except OSError:
        today_dosed, last_dose_epoch = 0.0, 0
    except Exception as exc:
        print("Dose ledger invalid:", type(exc).__name__)
        return False
    last_day = current_day
    state_ready = True
    save_state()
    return True


def dose(ml):
    global today_dosed, last_dose_ticks, last_dose_epoch
    ml = float(ml)
    if not state_ready or not rtc_valid():
        return False, 0.0, "RTC or persistent dose ledger is not ready"
    gap = time.time() - last_dose_epoch if last_dose_epoch else MIN_DOSE_GAP_SECONDS
    if ml <= 0 or ml > MAX_SINGLE_ML:
        return False, 0.0, "single-dose limit"
    if today_dosed + ml > MAX_DAILY_ML:
        return False, 0.0, "daily-dose limit"
    if gap < MIN_DOSE_GAP_SECONDS:
        return False, 0.0, "minimum dose interval"
    try:
        seconds = seconds_for_ml(ml)
    except ValueError as exc:
        return False, 0.0, str(exc)
    today_dosed += ml
    last_dose_epoch = time.time()
    try:
        save_state()
    except Exception as exc:
        today_dosed -= ml
        last_dose_epoch = 0
        return False, 0.0, str(exc)
    try:
        pump_on(True)
        time.sleep(seconds)
    finally:
        pump_on(False)
    last_dose_ticks = time.ticks_ms()
    return True, seconds, "completed"


def reset_daily_counter():
    global today_dosed, last_day
    if not state_ready or not rtc_valid():
        return False
    day = list(time.localtime()[:3])
    if day != last_day:
        today_dosed, last_day = 0.0, day
        save_state()
    return True


def handle_web_command(command):
    if command.get("command") != "dose":
        return False, {"reason": "command is not allow-listed in chapter 9"}
    ml = (command.get("parameters") or {}).get("ml", 0)
    success, seconds, reason = dose(ml)
    return success, {"dose_ml": ml, "runtime_seconds": seconds, "reason": reason, "local_safety_checked": True}


def main():
    pump_on(False)
    load_state()
    while True:
        rtc_valid = reset_daily_counter()
        if rtc_valid and time.localtime()[3] == 9 and today_dosed == 0.0:
            success, seconds, reason = dose(DAILY_DOSE_ML)
            print("scheduled dose:", success, seconds, reason)
            if web:
                web.send_event("dosing.completed" if success else "dosing.blocked", "info" if success else "warning", "Scheduled dosing result", reason, {"dose_ml": DAILY_DOSE_ML})
        print("pump_model: ml_per_sec={:.3f}, intercept={:.3f}, r2={:.3f}, today={:.2f} mL".format(ML_PER_SEC, INTERCEPT, CALIBRATION_R2, today_dosed))
        if web:
            web.send_readings([
                {"metric": "dose_ml", "value": round(today_dosed, 2), "unit": "mL/day", "status": "normal" if rtc_valid else "warning"},
                {"metric": "pump_flow_ml_s", "value": round(ML_PER_SEC, 3), "unit": "mL/s", "status": "normal"},
            ], {"chapter": 9, "calibration_r2": CALIBRATION_R2, "rtc_valid": rtc_valid})
            web.poll_command(handle_web_command)
        time.sleep(60)


if __name__ == "__main__":
    main()
