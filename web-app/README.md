# 智慧魚缸 Web Dashboard

這是一套 LAN-first 的 ESP32／MicroPython 智慧魚缸 Web App。公開首頁集中顯示即時感測值、狀態分級、歷史曲線、獨立預測與事件；登入後才可查看裝置設定、建立控制命令、排程、API 金鑰、資料庫管理與權限。

> 只有本 `web-app/` 專案採 CC BY 4.0。課程教材、教學圖片與原始素材不在授權範圍內，詳見 [NOTICE.md](NOTICE.md)。

## 功能

- 公開、響應式 Dashboard：手機到桌面、淺／深色、可拖曳／隱藏圖卡。
- 狀態顏色：正常綠、輕度異常橘、異常紅、缺失灰；歷史圖亦依狀態分段。
- 泛用感測欄位：同一套 API 可接水溫、水位、水質、光照、餵食、滴定、缺氧風險、影像／TinyML 結果與未來裝置。
- 預測與控制預設分離；預測只提供資訊，不會自動送出命令。
- SQLite WAL、稽核紀錄、ZIP 備份與 CSV 匯出。
- 原始資料預設保留 1095 天；管理員可調整 90–1825 天並查看實際資料庫空間。
- `viewer`、`operator`、`admin` 三種角色，HTTP-only session、CSRF 與裝置 API key。
- IoT 裝置輪詢命令並回報 ACK；裝置端仍必須執行本機安全規則。
- 五欄 cron 排程、裝置離線偵測、選用 MQTT bridge、可擴充警報 outbox API。

## 五分鐘啟動（Windows PowerShell）

需求：Python 3.11 以上。

```powershell
cd web-app
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
$env:AQUARIUM_ADMIN_PASSWORD = "請換成至少 12 字元的密碼"
.\.venv\Scripts\python.exe -m aquarium_app serve
```

開啟 `http://127.0.0.1:8000`。同一個家用網路的裝置可使用主機 LAN IP，例如 `http://192.168.1.20:8000`。

若未提供 `AQUARIUM_ADMIN_PASSWORD`，第一次啟動會產生隨機密碼並寫入 `data/initial-admin.txt`；登入後應立即建立自己的管理員帳號，再妥善移除該檔案。正式環境建議明確設定密碼。

加入可辨識的示範資料：

```powershell
.\.venv\Scripts\python.exe -m aquarium_app seed-demo
```

示範資料會帶有 `source=demo`，UI 會明確標示，避免被誤認為真實量測。

## Docker Compose

```powershell
Copy-Item .env.example .env
# 編輯 .env，至少更換 AQUARIUM_ADMIN_PASSWORD
docker compose up -d --build
```

資料保存在 `aquarium-data` volume。不要使用 `docker compose down -v`，除非確定要刪除資料。

## 文件

- [部署指南](docs/DEPLOYMENT.md)：Windows、macOS、Linux、Raspberry Pi、Docker 與 LAN／HTTPS。
- [IoT 裝置 API](docs/DEVICE_API.md)：金鑰、telemetry、事件、命令與 ACK。
- [安全模型](docs/SECURITY.md)：權限、網路邊界、備份與裝置端安全。
- [警報擴充 API](docs/ALARM_ADAPTER.md)：未來 LINE、WhatsApp 或其他通知 adapter 的介面。
- [ESP32 HTTP 範例](examples/esp32_http_client.py)：原創、獨立於課程素材的最小整合範例。

FastAPI 亦會提供互動式 API 文件：登入環境啟動後開啟 `/docs`。

## 測試

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=aquarium_app
node --check aquarium_app/static/app.js
```

## 重要安全界線

Dashboard 命令只代表「要求執行」。ESP32 必須再檢查感測器是否合理、液位／溫度上限、最大連續運轉時間、冷卻時間與實體緊急停止。不要讓雲端預測或網路中斷繞過這些規則。

