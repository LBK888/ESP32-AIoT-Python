# IoT 裝置 API

## 連線與認證

1. 管理員登入後台，為指定裝置建立 API key。
2. 金鑰只會顯示一次；伺服器只保存 SHA-256 digest。
3. ESP32 將完整金鑰放在 `Authorization: Bearer <key>`。
4. 每個裝置使用獨立金鑰。疑似外洩時先建立替代金鑰、更新裝置，再撤銷舊金鑰。

LAN HTTP 只能防止未持有金鑰者呼叫 API，無法防止同網路側錄；不可信任網路請使用 HTTPS。

## 取得裝置設定

```http
GET /api/v1/device/config
Authorization: Bearer aqk_...
```

回應包含裝置設定、排程、建議輪詢秒數與 `control_authority: local-safety-first`。

## 上傳 telemetry

```http
POST /api/v1/device/telemetry
Authorization: Bearer aqk_...
Content-Type: application/json

{
  "ts": 1785715200,
  "readings": [
    {"metric": "water_temperature", "value": 26.4, "unit": "°C", "status": "normal"},
    {"metric": "water_level", "value": 77.8, "unit": "%", "status": "warning"}
  ],
  "metadata": {"firmware": "1.0.0", "rssi": -61}
}
```

`ts` 可使用 UTC ISO 8601、Unix seconds、Unix milliseconds 或 `null`。`status` 只能是 `normal`、`warning`、`danger`、`missing`。Dashboard 與折線圖均直接使用這個狀態分級；缺失資料可傳 `value: null, status: missing`。

`metric` 是泛用識別字，可加入未來感測器，不需要修改資料表。建議穩定使用英文 snake_case，顯示名稱與圖表設定由後台管理。

## 回報事件

```http
POST /api/v1/device/events
Authorization: Bearer aqk_...
Content-Type: application/json

{
  "event_type": "topoff.blocked",
  "severity": "warning",
  "title": "補水已由本機安全規則阻擋",
  "detail": "浮球開關讀值矛盾，未啟動幫浦",
  "payload": {"float_high": true, "float_low": true}
}
```

若後台開啟 Alarm API，`warning`／`danger` 事件也會進入 alarm outbox。

## 命令輪詢與 ACK

```http
GET /api/v1/device/commands/next
Authorization: Bearer aqk_...
```

沒有命令時回傳 `{"command": null}`。取得命令後，裝置依序：

1. 驗證命令在本機 allowlist。
2. 檢查感測器、新鮮度、上下限、冷卻時間與最大運轉時間。
3. 執行或拒絕。
4. 回報結果。

```http
POST /api/v1/device/commands/{command_id}/ack
Authorization: Bearer aqk_...
Content-Type: application/json

{"success": false, "result": {"reason": "high-water interlock"}}
```

已 ACK 或逾時的命令不會再次領取。網路中斷時，裝置不得將「沒有新命令」解讀成維持危險輸出。

## MQTT 相容橋接（選用）

安裝 `pip install -e ".[mqtt]"` 並設定 `AQUARIUM_MQTT_ENABLED=true`。橋接器訂閱：

- `aquarium/<device-id>/telemetry`
- `aquarium/<device-id>/event`

telemetry 可使用與 HTTP 相同的 `readings` payload，也接受扁平 numeric key 的相容格式。MQTT broker 本身仍應設定帳密、ACL 與 TLS；HTTP Bearer key 不會自動成為 MQTT 認證。

