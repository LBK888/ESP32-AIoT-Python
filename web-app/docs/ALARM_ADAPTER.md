# 警報 Adapter API（擴充點）

本版不綁定任何通訊平台。它提供持久化 outbox，讓後續專案可自行加入 LINE、WhatsApp、Email、Telegram、Home Assistant 或其他通知 adapter，而不必更動裝置上傳流程。

## 流程

1. 管理員在後台啟用 `alarm_api_enabled`。
2. 裝置送出的 `warning`／`danger` 事件會自動建立 pending alarm；operator 也可用 `POST /api/v1/manage/alarms` 建立。
3. 已登入的 operator／admin 呼叫 `POST /api/v1/manage/alarms/claim?limit=20`，一次領取工作。
4. adapter 向外部服務送出訊息。
5. 呼叫 `POST /api/v1/manage/alarms/{id}/complete`，傳送 `{"sent": true, "result": {...}}` 或失敗原因。

管理 API 使用 session cookie 與 CSRF，不應把管理員密碼或 cookie 寫入公開原始碼。實作無人值守 adapter 時，建議在下一版加入專用、可撤銷且 scope 僅限 alarm 的 service token，或讓 adapter 與 App 在同一台主機上透過受限的內部介面溝通；不要重用 ESP32 device key。

## Adapter 應處理的行為

- 以 alarm `id` 做冪等鍵，避免 retry 重複通知。
- 依平台 rate limit 做 exponential backoff。
- 對 `danger` 與 `warning` 使用不同優先等級。
- 記錄外部 message id，但不要把平台 access token寫入 `result`。
- 設計靜音時段、重複事件合併與解除警報通知。

目前 UI 可檢視 outbox 狀態，資料庫備份亦包含 alarm 紀錄。這是刻意保留的 API 邊界，並不宣稱已內建任何第三方平台整合。
