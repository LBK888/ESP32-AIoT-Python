# 部署指南

## 先選部署方式

測試與教學優先使用區域網路：Dashboard 主機與 ESP32 位於同一個可信任 Wi-Fi／VLAN，不做路由器 port forwarding。長期使用可選原生 Python 或 Docker；若要跨網際網路存取，請先加入 HTTPS reverse proxy 或 VPN，並將 `AQUARIUM_COOKIE_SECURE=true`。

SQLite 適合單一 Web App process。不要以多個 Uvicorn worker 同時跑同一個資料庫，也不要把 SQLite 放在不支援可靠鎖定的網路磁碟。

## Windows 10／11

```powershell
cd web-app
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
$env:AQUARIUM_ADMIN_PASSWORD = "一組新的長密碼"
$env:AQUARIUM_ALLOWED_ORIGINS = "http://127.0.0.1:8000,http://192.168.1.20:8000"
.\.venv\Scripts\python.exe -m aquarium_app serve
```

用 `ipconfig` 找 IPv4 位址，並只在「私人網路」防火牆設定中允許 TCP 8000。若希望開機啟動，可用 Windows 工作排程器執行虛擬環境內的 Python；工作目錄設為 `web-app`。

## macOS

```bash
cd web-app
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
export AQUARIUM_ADMIN_PASSWORD='一組新的長密碼'
export AQUARIUM_ALLOWED_ORIGINS='http://127.0.0.1:8000,http://192.168.1.20:8000'
./.venv/bin/python -m aquarium_app serve
```

在「系統設定 → 網路」查看 LAN IP。若 macOS 詢問是否允許 Python 接受連線，只對可信任私人網路開放。

## Linux／Raspberry Pi OS

```bash
cd web-app
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
export AQUARIUM_ADMIN_PASSWORD='一組新的長密碼'
./.venv/bin/python -m aquarium_app serve
```

systemd 可使用以下核心設定，請依實際路徑與帳號修改：

```ini
[Unit]
Description=Smart Aquarium Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=aquarium
WorkingDirectory=/opt/smart-aquarium/web-app
Environment=AQUARIUM_ADMIN_PASSWORD=replace-this
ExecStart=/opt/smart-aquarium/web-app/.venv/bin/python -m aquarium_app serve
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

正式使用不要把密碼直接留在 world-readable unit；改用權限為 `0600` 的 `EnvironmentFile`。

## Docker／Docker Compose

1. 複製 `.env.example` 為 `.env`，更換管理員密碼與 origins。
2. 執行 `docker compose up -d --build`。
3. 用 `docker compose ps` 檢查 health，用 `docker compose logs -f dashboard` 查看紀錄。
4. 更新前先從後台下載 ZIP 備份，再執行 `docker compose up -d --build`。

Compose 使用 named volume 保存 `/app/data`。`docker compose down` 不會刪除 volume；`docker compose down -v` 會永久刪除，請審慎使用。

## 反向代理與 HTTPS

LAN 測試可以使用 HTTP，但 API key、密碼與命令會以明文經過 Wi-Fi。只要網路內存在不受信任的使用者，或要從外部連線，就應使用 Caddy／Nginx／Traefik 終止 TLS，並設定：

```text
AQUARIUM_COOKIE_SECURE=true
AQUARIUM_ALLOWED_ORIGINS=https://aquarium.example.net
```

代理只需轉送至單一 `127.0.0.1:8000` process。不要直接把 8000 port 暴露到公網；優先使用 VPN 或零信任連線。

## 備份、保留與容量估算

後台會顯示 SQLite 主檔、WAL、SHM 合計的實際空間與可回收頁面。預設原始資料保存 1095 天，管理員可設 90–1825 天。清理會刪除超過期限的 readings、舊 session、audit 與已處理 alarm；勾選 VACUUM 才會進一步壓縮檔案。

ZIP 匯出包含一致性的 SQLite backup、readings／events／commands CSV、設定與裝置 JSON。至少保留一份不在主機上的加密備份，並定期做還原演練。

## 來源參考

- FastAPI 官方建議從官方 Python image 自行建立 container，並使用 exec-form CMD：<https://fastapi.tiangolo.com/deployment/docker/>
- Uvicorn 使用 `--host 0.0.0.0` 才會接受 LAN 連線：<https://www.uvicorn.org/settings/>
- Python `venv` 官方說明：<https://docs.python.org/3/library/venv.html>
- Docker Compose 與持久化 volume：<https://docs.docker.com/compose/gettingstarted/>

