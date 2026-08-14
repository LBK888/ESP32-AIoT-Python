"""Optional Web App settings shared by all chapter examples.

Leave WEB_APP_ENABLED as False to run every example locally without Wi-Fi.
When enabled, copy the one-time API key created for each Web App device into
DEVICE_API_KEYS.  Do not commit real passwords or API keys.
"""

WEB_APP_ENABLED = False

WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"

# Either set WEB_APP_BASE_URL directly, or edit scheme/host/port separately.
WEB_APP_BASE_URL = ""
WEB_APP_SCHEME = "http"
WEB_APP_HOST = "192.168.1.20"
WEB_APP_PORT = 8000

# The Web App binds each key to exactly one device.
DEVICE_API_KEYS = {
    "temp-01": "aqk_REPLACE_ME",
    "level-01": "aqk_REPLACE_ME",
    "light-01": "aqk_REPLACE_ME",
    "feed-01": "aqk_REPLACE_ME",
    "dose-01": "aqk_REPLACE_ME",
    "quality-01": "aqk_REPLACE_ME",
    "color-01": "aqk_REPLACE_ME",
    "air-01": "aqk_REPLACE_ME",
    "ai-01": "aqk_REPLACE_ME",
    "gateway-01": "aqk_REPLACE_ME",
}

WEB_APP_TELEMETRY_SECONDS = 15
WEB_APP_COMMAND_SECONDS = 5
WEB_APP_WIFI_TIMEOUT_SECONDS = 15
WEB_APP_HTTP_TIMEOUT_SECONDS = 8
WEB_APP_QUEUE_SIZE = 12

# Chapter 14 MQTT settings.  Enable the bridge in the Web App separately.
MQTT_HOST = "192.168.1.20"
MQTT_PORT = 1883
MQTT_USERNAME = ""
MQTT_PASSWORD = ""

