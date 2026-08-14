from machine import Pin, I2C
import time

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("gateway-01")
except (ImportError, Exception):
    web = None

I2C_ID = 0
SDA_PIN = 21
SCL_PIN = 22
LCD_ADDR = 0x27

MASK_RS = 0x01
MASK_E = 0x04
MASK_BACKLIGHT = 0x08


class LCD1602:
    def __init__(self, i2c, addr=0x27):
        self.i2c = i2c
        self.addr = addr
        self.backlight = MASK_BACKLIGHT
        time.sleep_ms(50)
        for cmd in (0x33, 0x32, 0x28, 0x0C, 0x06, 0x01):
            self.command(cmd)
        time.sleep_ms(5)

    def _write4(self, data):
        self.i2c.writeto(self.addr, bytes([data | self.backlight | MASK_E]))
        time.sleep_us(500)
        self.i2c.writeto(self.addr, bytes([(data | self.backlight) & ~MASK_E]))
        time.sleep_us(100)

    def _send(self, value, rs=0):
        high = value & 0xF0
        low = (value << 4) & 0xF0
        self._write4(high | rs)
        self._write4(low | rs)

    def command(self, value):
        self._send(value, 0)

    def putchar(self, char):
        self._send(ord(char), MASK_RS)

    def clear(self):
        self.command(0x01)
        time.sleep_ms(2)

    def move_to(self, col, row):
        offsets = [0x00, 0x40]
        self.command(0x80 | (col + offsets[row]))

    def putstr(self, text, col=0, row=0):
        self.move_to(col, row)
        text = text[:16].ljust(16)
        for ch in text:
            self.putchar(ch)


def classify(temp_c, level_ok):
    if not level_ok:
        return "LEVEL ALERT"
    if temp_c < 22 or temp_c > 29:
        return "TEMP WARN"
    return "AQUARIUM OK"


def read_demo_data(tick):
    temp = 26.0 + (tick % 10) * 0.1
    level_ok = (tick % 17) != 0
    return temp, level_ok


def main():
    i2c = I2C(I2C_ID, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=100000)
    devices = i2c.scan()
    print("I2C devices:", [hex(x) for x in devices])
    if LCD_ADDR not in devices:
        raise RuntimeError("LCD not found; check SDA/SCL/address/power")
    lcd = LCD1602(i2c, LCD_ADDR)
    tick = 0
    failures = 0
    while True:
        temp, level_ok = read_demo_data(tick)
        try:
            lcd.putstr("Temp:{:5.2f} C".format(temp), 0, 0)
            lcd.putstr(classify(temp, level_ok), 0, 1)
            failures = 0
        except OSError as exc:
            failures += 1
            print("LCD I2C error:", type(exc).__name__, "count=", failures)
        if web:
            web.send_readings([
                {"metric": "temp_c", "value": round(temp, 2), "unit": "°C", "status": "normal"},
                {"metric": "level_low", "value": 0 if level_ok else 1, "unit": "bool", "status": "normal" if level_ok else "warning"},
                {"metric": "mode", "value": "local_dashboard_demo", "unit": "", "status": "normal"},
            ], {"chapter": 4, "i2c_errors": failures, "simulated": True})
        tick += 1
        time.sleep(1)


if __name__ == "__main__":
    main()
