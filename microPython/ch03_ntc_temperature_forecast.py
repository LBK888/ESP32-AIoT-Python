from machine import ADC, Pin
import time

from sensor_utils import adc_summary, ntc_celsius, status_for_range

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("temp-01")
except (ImportError, Exception):
    web = None

ADC_PIN = 34
R_FIXED = 10000.0
R0 = 10000.0
T0_K = 25.0 + 273.15
BETA = 3950.0
VREF = 3.3
SAMPLE_INTERVAL_S = 5
FORECAST_MINUTES = 30

adc = ADC(Pin(ADC_PIN))
adc.atten(ADC.ATTN_11DB)
adc.width(ADC.WIDTH_12BIT)
history = []
ewma = None


def adc_average(n=31):
    return adc_summary(adc, n, 5)


def ntc_temperature_c(raw):
    return ntc_celsius(raw, R_FIXED, R0, BETA, VREF)


def forecast_temperature(records, minutes):
    if len(records) < 12:
        return None, None, None
    xs = [t for t, _ in records]
    ys = [temp for _, temp in records]
    xbar = sum(xs) / len(xs)
    ybar = sum(ys) / len(ys)
    denom = sum((x - xbar) ** 2 for x in xs)
    if denom == 0:
        return ys[-1], 0.0, 0.0
    slope = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / denom
    fitted = [ybar + slope * (x - xbar) for x in xs]
    total = sum((y - ybar) ** 2 for y in ys)
    residual = sum((y - fit) ** 2 for y, fit in zip(ys, fitted))
    r2 = 0.0 if total == 0 else max(0.0, 1.0 - residual / total)
    # Do not present a long extrapolation when the recent trend is noisy.
    prediction = ys[-1] + slope * minutes if r2 >= 0.50 and abs(slope) <= 0.25 else None
    return prediction, slope, r2


def main():
    global history, ewma
    started = time.ticks_ms()
    while True:
        stats = adc_average()
        temp = ntc_temperature_c(stats["median"])
        status = status_for_range(temp, 22.0, 29.0, 0.0, 45.0)
        if stats["rail"] or stats["std"] > 35:
            temp, status = None, "missing"
        if temp is not None:
            ewma = temp if ewma is None else 0.2 * temp + 0.8 * ewma
            elapsed_min = time.ticks_diff(time.ticks_ms(), started) / 60000
            history.append((elapsed_min, ewma))
            history = history[-120:]
        pred, slope, r2 = forecast_temperature(history, FORECAST_MINUTES)
        if temp is None:
            print("temperature missing: check NTC divider and wiring")
        else:
            msg = "raw={:.0f}, temp={:.2f} C, smooth={:.2f} C".format(stats["median"], temp, ewma)
            if pred is not None:
                msg += ", forecast_{}min={:.2f} C (r2={:.2f})".format(FORECAST_MINUTES, pred, r2)
            print(msg)
        if web:
            readings = [
                {"metric": "temp_c", "value": None if temp is None else round(temp, 2), "unit": "°C", "status": status},
                {"metric": "temp_smoothed_c", "value": None if ewma is None else round(ewma, 2), "unit": "°C", "status": status},
                {"metric": "temp_forecast_c", "value": None if pred is None else round(pred, 2), "unit": "°C", "status": status if pred is not None else "missing"},
            ]
            web.send_readings(readings, {"chapter": 3, "forecast_r2": r2, "slope_c_per_min": slope})
        time.sleep(SAMPLE_INTERVAL_S)


if __name__ == "__main__":
    main()
