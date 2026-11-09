# Civitai-Buzz

每天自動在 <https://civitai.red/generate> 領取 **25 Buzz**。容器啟動後領取，領到即結束（進程結束 → 容器停止），不需手動開瀏覽器。

參考 [simao-silva/noip-renewer](https://github.com/simao-silva/noip-renewer) 的作法：Docker + Selenium + 環境變數憑證 + 跑完就退出。差別在於目標網站是 Civitai，登入方式是瀏覽器 Cookie。

## 運作原理

「Claim 25 Buzz」按鈕只是表層，實際動作是 tRPC mutation `buzz.claimDailyBoostReward`，伺服器端冪等（重複呼叫不會重複給點，重試安全）。

流程：

1. 以 `CIVITAI_COOKIE` 灌入 cookie（`.civitai.red`、`.civitai.com`）。
2. 開啟 `/generate`，等待 Cloudflare 挑戰自動通過。
3. 呼叫 `user.userRewardDetails` 檢查 `dailyBoost`：
   - `awarded > 0`：今天已領，exit 0。
   - `awardedCount === 0`：`POST buzz.claimDailyBoostReward`。
4. 重新查詢確認 `awarded > 0`（最多等 `CLAIM_TIMEOUT` 秒），成功則 exit 0。
5. API 失敗時退回 DOM 點擊「Claim 25 Buzz」按鈕，再用 API 驗證。

容器主進程就是 `buzz.py`，結束即停止；`restart: "no"` 避免自動重啟。

> 未知：Cloudflare 對資料中心 IP（VPS／雲端）是否要求 `cf_clearance`；站方若改 tRPC 名稱或 payload，API 路徑會失效（已保留 DOM 退路）。

## 取得 Cookie 與 User-Agent

1. 用 Chrome／Edge 登入 <https://civitai.red/>。
2. `F12` → **Network** → 重新整理 → 點任一 `civitai.red` 請求 → 複製 **Request Headers** 的整段 `Cookie`（含 `__Secure-civ-*`）。
3. Console 執行 `navigator.userAgent` 取得 User-Agent。

`__Secure-civ-token` 約一個月過期，過期後重新抓取即可。

## 快速開始

### Docker（建議）

```bash
docker build -t civitai-buzz .

docker run --rm \
  -e CIVITAI_COOKIE='<整段 Cookie>' \
  -e USER_AGENT='<你的 User-Agent>' \
  civitai-buzz
```

`--rm` 會在結束後刪除容器；若要保留日誌，去掉 `--rm` 並用 `docker logs` 查看。

### Docker Compose

```bash
export CIVITAI_COOKIE='...'
export USER_AGENT='...'
docker compose up --build
```

compose 直接傳入 shell 變數，專案內不需要 `.env`。

### Windows（不用 Docker）

雙擊 `run.bat`，依提示輸入 cookie 與 User-Agent（後者可直接 Enter 跳過）。首次執行會自動建立 `.venv` 並安裝依賴。

## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `CIVITAI_COOKIE` | **必填** | 整段 Cookie header |
| `USER_AGENT` | 空 | 空 = 瀏覽器預設；建議與產生 cookie 的瀏覽器一致 |
| `CIVITAI_URL` | `https://civitai.red/generate` | 只給網域會自動補 `/generate` |
| `HEADLESS` | `true` | `false` = Xvfb + 有頭 Chrome（最像真瀏覽器） |
| `CF_TIMEOUT` | `90` | 等待 Cloudflare 挑戰的秒數 |
| `CLAIM_TIMEOUT` | `300` | 等待獎勵入帳的秒數 |
| `POLL_INTERVAL` | `1.0` | 輪詢間隔（秒） |
| `STRICT` | `false` | `true` = 沒領到就 exit 1 |
| `DEBUG` | `false` | 失敗時把截圖與 DOM 存到 `artifacts/` |
| `RUN_TIMEOUT` | `900` | 容器內硬性上限，避免卡死 |

## 退出碼

| 代碼 | 意義 |
|---|---|
| `0` | 已領取，或今天已領過 |
| `1` | 失敗：Cloudflare、cookie 失效、瀏覽器錯誤 |
| `2` | 設定錯誤：缺少或格式錯誤的 cookie |

只檢查狀態、不領取：

```bash
docker run --rm -e CIVITAI_COOKIE='...' -e USER_AGENT='...' civitai-buzz --check
```

## 每日排程

Linux cron（環境檔放在專案外）：

```cron
30 9 * * * docker run --rm --env-file /etc/civitai-buzz.env civitai-buzz >> /var/log/civitai-buzz.log 2>&1
```

Windows 工作排程器：程式填 `run.bat`（排程用請移除最後的 `pause`）。

## 疑難排解

| 症狀 | 處理 |
|---|---|
| 一直停在 Cloudflare | 重抓 cookie、對齊 `USER_AGENT`，在產生 cookie 的同一台機器／網路執行；必要時 `HEADLESS=false` |
| `Cookie rejected (HTTP 401)` | `__Secure-civ-token` 已過期，重新登入並複製新 Cookie |
| `dailyBoost` 不見 | 帳號可能不適用或站方改了型別；`STRICT=false` 時會 exit 0 |
| API 與 DOM 都失敗 | 開 `DEBUG=true` 查看 `artifacts/`，或改用 `HEADLESS=false` |
| 確認是否領到 | `buzz.getBuzzAccount` 的 blue 餘額 +25，且 `dailyBoost.awarded` 為 25 |

## 專案結構

```
.
├── buzz.py               # cookie → /generate → tRPC 領取（DOM 為退路）
├── entrypoint.sh         # HEADLESS=false 時套 Xvfb；跑完即退出
├── run.bat               # Windows 一鍵執行
├── Dockerfile            # Debian + Chromium + chromedriver + Xvfb
├── docker-compose.yml
├── requirements.txt
└── .github/workflows/docker.yml
```

## 安全與免責

- Cookie 等同帳號憑證，請視同密碼：只透過 `-e`／shell 環境變數傳入，不寫入 Dockerfile、image、compose 或 git；程式不會將其印進日誌。`.gitignore`／`.dockerignore` 已排除 `.env`、`artifacts/`。
- 僅供**自己的帳號**、每天一次使用。本專案為瀏覽器自動化，站方改版或 Cloudflare 政策變動可能導致失效，與 Civitai 官方無關，風險自負。

## License

MIT，見 [LICENSE](LICENSE)。
