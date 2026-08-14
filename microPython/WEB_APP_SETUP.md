# MicroPython 連接整合 Web App

## 最短設定流程

1. 在 Web App 的管理畫面替裝置建立 API key。API key 只顯示一次，而且綁定單一裝置。
2. 將 `web_app_config.py`、`web_app_client.py`、`sensor_utils.py` 與要執行的章節程式上傳到 ESP32 根目錄。
3. 編輯 `web_app_config.py`：
   - 將 `WEB_APP_ENABLED` 改為 `True`。
   - 填入 `WIFI_SSID`、`WIFI_PASSWORD`。
   - 若主機與 port 分開設定，填入 `WEB_APP_HOST`、`WEB_APP_PORT`；若有反向代理或特殊路徑，直接填完整 `WEB_APP_BASE_URL`。
   - 將該章所使用裝置的 key 填入 `DEVICE_API_KEYS`。
4. 先在電腦瀏覽器開啟 Web App URL，確認 ESP32 與 Web App 主機在可互通的網路，再執行章節程式。

各章預設裝置：第 3、10、14 章為 `temp-01`；第 5、6 章為 `level-01`；第 7 章為 `light-01`；第 8 章為 `feed-01`；第 9 章為 `dose-01`；第 11 章為 `quality-01`；第 12 章為 `color-01`；第 13 章為 `air-01`；第 15 章為 `ai-01`；第 1、2、4、16 章為 `gateway-01`。

## URL 與 port 範例

一般區域網路：

```python
WEB_APP_BASE_URL = ""
WEB_APP_SCHEME = "http"
WEB_APP_HOST = "192.168.1.20"
WEB_APP_PORT = 8000
```

HTTPS 反向代理：

```python
WEB_APP_BASE_URL = "https://aquarium.example.edu"
```

ESP32 不能用 `localhost` 連到電腦；`localhost` 在 ESP32 上代表 ESP32 自己。請填 Web App 主機的 LAN IP 或可解析的網域名稱。

## 不使用或移除 Web App

最簡單的方法是保留檔案但設定：

```python
WEB_APP_ENABLED = False
```

此時不會啟動 Wi-Fi、不會發 HTTP request，感測、顯示及本機安全控制照常執行。若要完全移除，刪除章節開頭有 `Optional` 註解的 import 區塊，以及主迴圈內的 `if web:` 區塊；再刪除 `web_app_client.py` 與 `web_app_config.py`。硬體函式沒有反向依賴 Web App 模組。

## 斷線行為

- 網路錯誤不會停止本機控制。
- telemetry 使用有限大小的記憶體佇列；滿載時捨棄最舊資料，避免 ESP32 RAM 被耗盡。
- 失敗後採指數退避，最長 60 秒再試。
- HTTP response 一律關閉並執行垃圾回收。
- 遠端命令必須通過各章本機 allowlist、時間／劑量／液位互鎖；Web App 不能繞過 ESP32 安全規則。
- Web App 不可達時不會收到遠端命令；本機排程與安全狀態仍繼續。

## MQTT（第 14 章）

第 14 章使用 `web_app_config.py` 的 `MQTT_HOST`、`MQTT_PORT`、帳號與密碼，發布到 `aquarium/temp-01/telemetry`。Web App 必須另行啟用 MQTT bridge，broker 也必須允許 ESP32 與 Web App 連線。MQTT topic 中的裝置 ID 必須已存在於 Web App。

## 安全提醒

教室 LAN 可先用 HTTP；跨不受信任網路時應使用 HTTPS/VPN，避免 Wi-Fi 密碼或 API key 被攔截。不要把填有真實密碼與 key 的 `web_app_config.py` 公開或提交版本控制。
