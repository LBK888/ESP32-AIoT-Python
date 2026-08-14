from machine import Pin, ADC
import time

from sensor_utils import adc_summary, clamp

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("gateway-01")
except (ImportError, Exception):
    web = None

LED_PIN = 2
BUTTON_PIN = 14
ADC_PIN = 34

led = Pin(LED_PIN, Pin.OUT)
button = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)
adc = ADC(Pin(ADC_PIN))
adc.atten(ADC.ATTN_11DB)
adc.width(ADC.WIDTH_12BIT)


def read_adc_stats(samples=31, delay_ms=5):
    stats = adc_summary(adc, samples, delay_ms)
    stats["voltage"] = stats["median"] * 3.3 / 4095
    # A transparent teaching score: rail contact is unusable; random variation
    # is penalized using robust MAD and standard deviation.
    penalty = stats["mad"] * 2.0 + stats["std"]
    stats["quality"] = 0 if stats["rail"] else clamp(100 - penalty, 0, 100)
    if stats["rail"]:
        stats["status"] = "missing"
    elif stats["std"] > 25 or stats["maximum"] - stats["minimum"] > 200:
        stats["status"] = "warning"
    else:
        stats["status"] = "normal"
    return stats


def main():
    while True:
        pressed = button.value() == 0
        led.value(1 if pressed else 0)
        stats = read_adc_stats()
        span = stats["maximum"] - stats["minimum"]
        print("button={}, adc_median={:.1f}, voltage={:.3f} V, std={:.1f}, span={}, quality={:.0f}, status={}".format(
            pressed, stats["median"], stats["voltage"], stats["std"], span,
            stats["quality"], stats["status"]
        ))
        if web:
            web.send_readings([
                {"metric": "adc_voltage_v", "value": round(stats["voltage"], 4), "unit": "V", "status": stats["status"]},
                {"metric": "adc_noise_std", "value": round(stats["std"], 2), "unit": "count", "status": stats["status"]},
                {"metric": "data_quality_pct", "value": round(stats["quality"], 1), "unit": "%", "status": stats["status"]},
            ], {"chapter": 2, "adc_pin": ADC_PIN})
        time.sleep(1)


if __name__ == "__main__":
    main()
