from machine import Pin, ADC
import math
import time

from sensor_utils import adc_summary, ntc_celsius

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("air-01")
except (ImportError, Exception):
    web = None

TEMP_ADC_PIN = 34
AIR_RELAY_PIN = 23
RELAY_ACTIVE = 1
RISK_ON, RISK_OFF = 0.65, 0.45
MAX_OFF_SECONDS = 30 * 60  # Fail-safe: uncertain/missing data enables aeration.

temp_adc = ADC(Pin(TEMP_ADC_PIN)); temp_adc.atten(ADC.ATTN_11DB); temp_adc.width(ADC.WIDTH_12BIT)
air = Pin(AIR_RELAY_PIN, Pin.OUT, value=1 - RELAY_ACTIVE)
last_feed_time = 0


def sigmoid(x):
    x = min(30, max(-30, x))
    return 1 / (1 + math.exp(-x))


def read_temperature():
    stats = adc_summary(temp_adc, 31, 5)
    if stats["rail"] or stats["std"] > 35:
        return None
    return ntc_celsius(stats["median"])


def do_risk(temp_c, hour, minutes_since_feed):
    if temp_c is None or hour is None:
        return None
    night = 1 if hour < 7 or hour >= 20 else 0
    feed_recent = 1 if minutes_since_feed < 180 else 0
    return sigmoid(-5.0 + 0.16 * temp_c + 1.1 * night + 0.8 * feed_recent)


def set_air(enabled):
    air.value(RELAY_ACTIVE if enabled else 1 - RELAY_ACTIVE)


def main():
    air_on = True
    last_air_on = time.ticks_ms()
    set_air(True)
    while True:
        rtc_valid = time.localtime()[0] >= 2024
        now = time.time()
        temp = read_temperature()
        hour = time.localtime()[3] if rtc_valid else None
        minutes_since_feed = (now - last_feed_time) / 60 if last_feed_time and rtc_valid else 999
        risk = do_risk(temp, hour, minutes_since_feed)
        if risk is None:  # Aeration is the safer output when evidence is missing.
            air_on = True
        elif not air_on and risk >= RISK_ON:
            air_on = True
        elif air_on and risk <= RISK_OFF:
            air_on = False
        if not air_on and time.ticks_diff(time.ticks_ms(), last_air_on) >= MAX_OFF_SECONDS * 1000:
            air_on = True
        if air_on:
            last_air_on = time.ticks_ms()
        set_air(air_on)
        status = "missing" if risk is None else "danger" if risk >= RISK_ON else "warning" if risk >= RISK_OFF else "normal"
        print("temp={}, hour={}, oxygen_risk={}, air={}".format(temp, hour, risk, air_on))
        if web:
            web.send_readings([
                {"metric": "temp_c", "value": None if temp is None else round(temp, 2), "unit": "°C", "status": "missing" if temp is None else "normal"},
                {"metric": "oxygen_risk", "value": None if risk is None else round(risk * 100, 1), "unit": "%", "status": status},
                {"metric": "aeration_on", "value": 1 if air_on else 0, "unit": "bool", "status": "normal"},
            ], {"chapter": 13, "model": "teaching-risk-model", "rtc_valid": rtc_valid})
        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    finally:
        set_air(True)
