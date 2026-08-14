# 安全模型

## 權限

- 公開 Dashboard：只讀即時值、歷史／預測、公開事件與裝置狀態；不提供控制。
- `viewer`：登入後查看管理資料，但不可改設定或控制。
- `operator`：可建立／取消控制命令與排程、處理 alarm outbox。
- `admin`：另可管理使用者、裝置、API keys、資料保留、清理與備份。

密碼使用隨機 salt 的 scrypt；登入成功後使用 HTTP-only、SameSite=Strict session cookie。所有變更端點另驗證 CSRF header。稽核表記錄登入、命令、設定、金鑰與資料庫操作。

## 裝置金鑰

裝置 key 是高熵 bearer secret，只在建立時顯示一次，SQLite 僅保存 digest。每台裝置應有獨立 key，避免把相同 secret 寫入所有韌體。key 不要提交 Git，也不要顯示在 serial log 或截圖。

## 控制界線

伺服器負責排程與命令佇列，不是最終安全控制器。ESP32 應保留：

- 命令 allowlist 與參數範圍。
- 感測器 freshness、合理性與互相矛盾檢查。
- 加熱溫度上限、補水高水位 interlock、滴定每日總量、餵食冷卻期。
- 所有 actuator 的最大連續運轉時間與斷線預設安全狀態。
- watchdog、實體保險／繼電器 fail-safe，以及可人工操作的緊急停止。

預測 API 帶有 `control_isolated=true`，前端也明確標示；不得由 UI 或 ESP32 將預測值直接轉成 actuator 命令。

## 網路與部署

測試以可信任 LAN 優先，不做 router port forwarding。HTTP 上的密碼、cookie 與 bearer key 可被同網路攻擊者側錄，因此跨不可信任網路必須使用 HTTPS 或 VPN，並設定 secure cookie。限制防火牆來源、更新主機、停用預設帳號，並定期撤銷不用的 key。

App 設定了基本 CSP、frame、MIME 與 referrer headers；這些不能取代 TLS、防火牆與 OS 更新。

## 資料與備份

原始資料預設保留三年，範圍為 90 天至五年。較長保存期會增加隱私與硬碟成本；管理員應查看後台的實際 physical bytes、定期匯出 ZIP、驗證可還原後再清理。備份含裝置／設定與歷史資料，需視為敏感檔案並加密保存。

## 回報弱點

公開發佈前請在 repository 加上私人安全聯絡方式。報告中不要附上可用的 API key、密碼、真實住址或公開可存取的魚缸網址。

