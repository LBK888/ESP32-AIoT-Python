from machine import Pin, I2C
import time

try:  # Optional: remove these four lines to remove Web App integration.
    from web_app_client import get_web_client
    web = get_web_client("color-01")
except (ImportError, Exception):
    web = None

SDA_PIN, SCL_PIN, ADDR = 21, 22, 0x29
COMMAND, ENABLE, ATIME, CONTROL, CDATA = 0x80, 0x00, 0x01, 0x0F, 0x14
SATURATION_COUNT = 65500
CHL_COEF = {"bias": 0.0, "r_norm": -18.0, "g_norm": 36.0, "b_norm": -8.0}

i2c = I2C(0, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=100000)


def write8(reg, val):
    i2c.writeto_mem(ADDR, COMMAND | reg, bytes([val]))


def read16(reg):
    data = i2c.readfrom_mem(ADDR, COMMAND | reg, 2)
    return data[0] | (data[1] << 8)


def init_sensor():
    devices = i2c.scan()
    if ADDR not in devices:
        raise RuntimeError("TCS34725 not found; check SDA/SCL/address/power")
    write8(ENABLE, 0x01)
    time.sleep_ms(3)
    write8(ENABLE, 0x03)
    write8(ATIME, 0xD5)
    write8(CONTROL, 0x01)
    time.sleep_ms(110)


def read_color(samples=5):
    channels = [[], [], [], []]
    for _ in range(samples):
        for index, reg in enumerate((CDATA, CDATA + 2, CDATA + 4, CDATA + 6)):
            channels[index].append(read16(reg))
        time.sleep_ms(110)
    return tuple(sum(values) / len(values) for values in channels)


def estimate_chlorophyll(c, r, g, b):
    if c < 10 or max(c, r, g, b) >= SATURATION_COUNT:
        return None, None, None, None
    rn, gn, bn = r / c, g / c, b / c
    score = CHL_COEF["bias"] + CHL_COEF["r_norm"] * rn + CHL_COEF["g_norm"] * gn + CHL_COEF["b_norm"] * bn
    return max(0, score), rn, gn, bn


def main():
    init_sensor()
    while True:
        try:
            c, r, g, b = read_color()
            chl, rn, gn, bn = estimate_chlorophyll(c, r, g, b)
            status = "missing" if chl is None else "warning" if chl > 20 else "normal"
            print("C={:.0f}, R={:.0f}, G={:.0f}, B={:.0f}, chl={}".format(c, r, g, b, chl))
        except OSError as exc:
            c = r = g = b = chl = rn = gn = bn = None
            status = "missing"
            print("TCS34725 read error:", type(exc).__name__)
            try:
                init_sensor()
            except Exception:
                pass
        if web:
            web.send_readings([
                {"metric": "chlorophyll_score", "value": None if chl is None else round(chl, 2), "unit": "relative", "status": status},
                {"metric": "color_clear", "value": None if c is None else round(c), "unit": "count", "status": status},
            ], {"chapter": 12, "r_norm": rn, "g_norm": gn, "b_norm": bn})
        time.sleep(5)


if __name__ == "__main__":
    main()
