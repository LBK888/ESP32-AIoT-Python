"""Pure-Python sensor statistics shared by the MicroPython examples."""

import math
import time


def clamp(value, low, high):
    return min(high, max(low, value))


def median(values):
    ordered = sorted(values)
    size = len(ordered)
    if not size:
        return None
    middle = size // 2
    if size % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def mean(values):
    return sum(values) / len(values) if values else None


def standard_deviation(values):
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def adc_samples(adc, count=31, delay_ms=4):
    values = []
    for _ in range(count):
        values.append(adc.read())
        time.sleep_ms(delay_ms)
    return values


def adc_summary(adc, count=31, delay_ms=4):
    values = adc_samples(adc, count, delay_ms)
    center = median(values)
    deviations = [abs(value - center) for value in values]
    return {
        "median": center,
        "mean": mean(values),
        "std": standard_deviation(values),
        "mad": median(deviations),
        "minimum": min(values),
        "maximum": max(values),
        "rail": center <= 8 or center >= 4087,
    }


def ntc_celsius(raw, r_fixed=10000.0, r0=10000.0, beta=3950.0, vref=3.3):
    """Convert the divider 3V3 -> fixed R -> ADC -> NTC -> GND."""
    if raw is None or raw <= 8 or raw >= 4087:
        return None
    voltage = raw * vref / 4095.0
    resistance = r_fixed * voltage / (vref - voltage)
    inv_kelvin = (1.0 / 298.15) + math.log(resistance / r0) / beta
    value = (1.0 / inv_kelvin) - 273.15
    return value if -10.0 <= value <= 60.0 else None


def status_for_range(value, normal_low, normal_high, valid_low, valid_high):
    if value is None or value < valid_low or value > valid_high:
        return "missing"
    if value < normal_low or value > normal_high:
        return "warning"
    return "normal"
