from machine import Pin, PWM, ADC
import time

from sensor_utils import adc_summary, ntc_celsius, status_for_range

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("temp-01")
except (ImportError, Exception):
    web = None

TEMP_ADC_PIN = 34  # ADC1 is available while Wi-Fi/Bluetooth is active.
HEATER_PIN = 25
COOLER_PIN = 26
SETPOINT_C = 26.0
HARD_LOW_C = 15.0
HARD_HIGH_C = 32.0
R_FIXED = 10000.0
R0 = 10000.0
BETA = 3950.0

adc = ADC(Pin(TEMP_ADC_PIN))
adc.atten(ADC.ATTN_11DB)
adc.width(ADC.WIDTH_12BIT)
heater = PWM(Pin(HEATER_PIN), freq=1000)
cooler = PWM(Pin(COOLER_PIN), freq=1000)


class PID:
    def __init__(self, kp, ki, kd, integral_limit=100):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.integral = 0.0
        self.last_measurement = None
        self.integral_limit = integral_limit

    def reset(self):
        self.integral = 0.0
        self.last_measurement = None

    def update(self, setpoint, measurement, dt):
        error = setpoint - measurement
        self.integral += error * dt
        self.integral = min(self.integral_limit, max(-self.integral_limit, self.integral))
        # Derivative on measurement avoids a derivative kick when setpoint moves.
        derivative = 0.0 if self.last_measurement is None else -(measurement - self.last_measurement) / dt
        self.last_measurement = measurement
        return self.kp * error + self.ki * self.integral + self.kd * derivative


def set_pwm(pwm, value):
    value = min(1023, max(0, int(value)))
    if hasattr(pwm, "duty_u16"):
        pwm.duty_u16(int(value * 65535 / 1023))
    else:
        pwm.duty(value)


def outputs_off():
    set_pwm(heater, 0)
    set_pwm(cooler, 0)


def read_temperature_c():
    stats = adc_summary(adc, 31, 5)
    value = ntc_celsius(stats["median"], R_FIXED, R0, BETA)
    if stats["rail"] or stats["std"] > 35:
        return None, stats
    return value, stats


pid = PID(kp=180, ki=3, kd=40)


def main():
    last = time.ticks_ms()
    outputs_off()
    while True:
        now = time.ticks_ms()
        dt = min(10.0, max(0.1, time.ticks_diff(now, last) / 1000))
        last = now
        temp, stats = read_temperature_c()
        status = status_for_range(temp, 22.0, 29.0, HARD_LOW_C, HARD_HIGH_C)
        if temp is None or status == "missing":
            outputs_off()
            pid.reset()
            heat_power = cool_power = 0.0
            print("FAULT: temperature sensor missing/out of safe range; outputs off")
        else:
            output = pid.update(SETPOINT_C, temp, dt)
            heat_raw = min(800, output) if output >= 0 else 0
            cool_raw = min(800, -output) if output < 0 else 0
            set_pwm(heater, heat_raw)
            set_pwm(cooler, cool_raw)
            heat_power, cool_power = heat_raw * 100 / 1023, cool_raw * 100 / 1023
            print("temp={:.2f} C, set={:.2f} C, heat={:.1f}%, cool={:.1f}%".format(temp, SETPOINT_C, heat_power, cool_power))
        if web:
            web.send_readings([
                {"metric": "temp_c", "value": None if temp is None else round(temp, 2), "unit": "°C", "status": status},
                {"metric": "heating_power_pct", "value": round(heat_power, 1), "unit": "%", "status": status},
                {"metric": "cooling_power_pct", "value": round(cool_power, 1), "unit": "%", "status": status},
            ], {"chapter": 10, "adc_std": stats["std"], "setpoint_c": SETPOINT_C})
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    finally:
        outputs_off()
