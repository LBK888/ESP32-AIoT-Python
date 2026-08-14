from machine import Pin, PWM, ADC
import time

from sensor_utils import adc_summary, median

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("feed-01")
except (ImportError, Exception):
    web = None

SERVO_PIN = 13
INTAKE_SENSOR_ADC = 35  # ADC1: remains available with Wi-Fi/Bluetooth
FEED_INTERVAL_S = 12 * 60 * 60
RESPONSE_WINDOW_S = 120
FEED_ON_BOOT = False
MAX_FEEDS_PER_DAY = 3

servo = PWM(Pin(SERVO_PIN), freq=50)
sensor = ADC(Pin(INTAKE_SENSOR_ADC))
sensor.atten(ADC.ATTN_11DB)
sensor.width(ADC.WIDTH_12BIT)
last_feed_ticks = time.ticks_add(time.ticks_ms(), -FEED_INTERVAL_S * 1000) if FEED_ON_BOOT else time.ticks_ms()
day_key = None
feeds_today = 0


def servo_angle(angle):
    angle = min(180, max(0, angle))
    pulse_us = 500 + angle * 2000 / 180
    if hasattr(servo, "duty_u16"):
        servo.duty_u16(int(pulse_us / 20000 * 65535))
    else:
        servo.duty(int(pulse_us / 20000 * 1023))


def servo_off():
    if hasattr(servo, "duty_u16"):
        servo.duty_u16(0)
    else:
        servo.duty(0)


def dispense():
    try:
        servo_angle(15)
        time.sleep_ms(500)
        servo_angle(85)
        time.sleep_ms(800)
        servo_angle(15)
        time.sleep_ms(500)
    finally:
        servo_off()


def feeding_response():
    baseline = adc_summary(sensor, 31, 15)
    if baseline["rail"] or baseline["std"] > 80:
        return None, "missing"
    changes = []
    started = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), started) < RESPONSE_WINDOW_S * 1000:
        sample = adc_summary(sensor, 9, 10)
        if not sample["rail"]:
            changes.append(abs(sample["median"] - baseline["median"]))
        time.sleep_ms(500)
    # Median change is robust to a hand, bubble, or one electrical spike.
    return median(changes), "normal" if changes else "missing"


def current_day_key():
    if time.localtime()[0] >= 2024:
        tm = time.localtime()
        return (tm[0], tm[1], tm[2])
    return time.ticks_ms() // 86400000


def feed_once():
    global last_feed_ticks, feeds_today, day_key
    new_day = current_day_key()
    if new_day != day_key:
        day_key, feeds_today = new_day, 0
    gap_s = time.ticks_diff(time.ticks_ms(), last_feed_ticks) / 1000
    if gap_s < FEED_INTERVAL_S:
        return False, None, "minimum feed interval not reached"
    if feeds_today >= MAX_FEEDS_PER_DAY:
        return False, None, "daily feed limit reached"
    dispense()
    score, sensor_status = feeding_response()
    last_feed_ticks = time.ticks_ms()
    feeds_today += 1
    return True, score, "response sensor " + sensor_status


def handle_web_command(command):
    if command.get("command") != "feed":
        return False, {"reason": "command is not allow-listed in chapter 8"}
    success, score, reason = feed_once()
    return success, {"feed_response_score": score, "reason": reason, "local_safety_checked": True}


def main():
    while True:
        due = time.ticks_diff(time.ticks_ms(), last_feed_ticks) >= FEED_INTERVAL_S * 1000
        if due:
            success, score, reason = feed_once()
            print("feed:", success, "response=", score, reason)
            if web:
                web.send_event("feeding.completed" if success else "feeding.blocked", "info" if success else "warning", "Feeding result", reason, {"response_score": score})
        if web:
            web.send_readings([
                {"metric": "feed_response_score", "value": score if due else None, "unit": "ADC Δ", "status": "normal" if due and score is not None else "missing"},
                {"metric": "feeds_today", "value": feeds_today, "unit": "count", "status": "normal"},
            ], {"chapter": 8})
            web.poll_command(handle_web_command)
        time.sleep(10)


if __name__ == "__main__":
    main()
