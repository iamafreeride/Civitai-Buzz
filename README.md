# Civitai-Buzz

[English](README_EN.md) | **繁體中文**

自動領取 <https://civitai.red/generate> 每日 **25 Buzz**。容器啟動、領取、結束，不必手動開瀏覽器。參考 [simao-silva/noip-renewer](https://github.com/simao-silva/noip-renewer)：Docker + Selenium + 環境變數傳入憑證 + 做完即結束。登入方式為瀏覽器 cookie。

## 運作方式

「Claim 25 Buzz」按鈕只是表面，真正的動作是 tRPC mutation `buzz.claimDailyBoostReward`，伺服器端具冪等性（重複呼叫不會多給，所以重試是安全的）。

1. 注入 `CIVITAI_COOKIE` 中的 cookie（`.civitai.red` 與 `.civitai.com`）。
2. 開啟 `/generate`，等待 Cloudflare 驗證自行通過。
3. 呼叫 `user.userRewardDetails` 檢查 `dailyBoost`：`awarded > 0` 表示今天已領（exit 0）；`awardedCount === 0` 則 `POST buzz.claimDailyBoostReward`。
4. 再查一次確認 `awarded > 0`（最多等 `CLAIM_TIMEOUT` 秒），成功即 exit 0。
5. 若 API 失敗，退而點擊 DOM 上的「Claim 25 Buzz」按鈕，並用 API 驗證。

> 未知項：資料中心 IP（VPS／雲端）是否需要 `cf_clearance`；網站若更改 tRPC 名稱或 payload，API 路徑會失效（因此保留 DOM 備援）。

## 取得 Cookie 與 User-Agent

1. 用 Chrome 或 Edge 登入 <https://civitai.red/>。
2. `F12` → **Network** → 重新整理 → 點任一個 `civitai.red` 請求 → 在 **Request Headers** 複製完整的 `Cookie` 值（包含 `__Secure-civ-*`）。
3. 在 Console 執行 `navigator.userAgent` 取得 User-Agent。

`__Secure-civ-token` 約一個月到期，到期時重新取得即可。

## 快速開始

### Docker（建議）

```bash
docker build -t civitai-buzz .

docker run --rm \
  -e CIVITAI_COOKIE='<完整 Cookie>' \
  -e USER_AGENT='<你的 User-Agent>' \
  civitai-buzz
```

想保留日誌就拿掉 `--rm`，再用 `docker logs` 查看。

### Docker Compose

```bash
export CIVITAI_COOKIE='...'
export USER_AGENT='...'
docker compose up --build
```

Compose 會直接傳遞 shell 變數，專案中不需要 `.env` 檔。

### Windows 本機（不用 Docker）

雙擊 `run.bat`，依提示輸入 cookie 與 User-Agent（後者可按 Enter 跳過）。第一次執行會自動建立 `.venv` 並安裝相依套件。

## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `CIVITAI_COOKIE` | **必填** | 完整 Cookie 標頭 |
| `USER_AGENT` | 空 | 空 = 瀏覽器預設；應與產生 cookie 的瀏覽器一致 |
| `CIVITAI_URL` | `https://civitai.red/generate` | 只給網域時會自動補上 `/generate` |
| `HEADLESS` | `true` | `false` = Xvfb + 有畫面的 Chrome（最像真實瀏覽器） |
| `CF_TIMEOUT` | `90` | 等 Cloudflare 驗證的秒數 |
| `CLAIM_TIMEOUT` | `300` | 等獎勵入帳的秒數 |
| `POLL_INTERVAL` | `1.0` | 輪詢間隔（秒） |
| `STRICT` | `false` | `true` = 沒領到就 exit 1 |
| `DEBUG` | `false` | 失敗時把截圖與 DOM 存到 `artifacts/` |
| `RUN_TIMEOUT` | `900` | 容器內的硬性逾時，避免卡住 |

## 退出碼

| 代碼 | 意義 |
|---|---|
| `0` | 已領取，或今天已領過 |
| `1` | 失敗：Cloudflare、cookie 無效、瀏覽器錯誤 |
| `2` | 設定錯誤：缺少 cookie 或格式不符 |

只查詢狀態、不領取：

```bash
docker run --rm -e CIVITAI_COOKIE='...' -e USER_AGENT='...' civitai-buzz --check
```

## 每日排程

Linux cron（env 檔請放在專案外）：

```cron
30 9 * * * docker run --rm --env-file /etc/civitai-buzz.env civitai-buzz >> /var/log/civitai-buzz.log 2>&1
```

Windows 工作排程器：執行 `run.bat`（請拿掉最後的 `pause`）。

## 疑難排解

| 症狀 | 處理 |
|---|---|
| 卡在 Cloudflare | 重新取得 cookie、對齊 `USER_AGENT`，並在產生 cookie 的同一台機器／網路執行；必要時用 `HEADLESS=false` |
| `Cookie rejected (HTTP 401)` | `__Secure-civ-token` 已過期，重新登入並複製新的 Cookie |
| 缺少 `dailyBoost` | 帳號可能不符資格，或網站改了型別；`STRICT=false` 時 exit 0 |
| API 與 DOM 都失敗 | 設 `DEBUG=true` 查看 `artifacts/`，或改用 `HEADLESS=false` |
| 驗證是否領到 | `buzz.getBuzzAccount` 的藍色餘額增加 25，且 `dailyBoost.awarded` 變成 25 |

## 專案結構

```
buzz.py               cookie → /generate → tRPC 領取（DOM 備援）
entrypoint.sh         HEADLESS=false 時包裝 Xvfb；做完即結束
run.bat               Windows 一鍵執行
Dockerfile            Debian + Chromium + chromedriver + Xvfb
docker-compose.yml
requirements.txt
.github/workflows/docker.yml
```

## 安全性與免責聲明

- 請把 cookie 當作密碼，等同帳號憑證。只透過 `-e`／shell 環境變數傳入，切勿寫進 Dockerfile、映像、compose 檔或 git。程式不會把它印到日誌，`.gitignore`／`.dockerignore` 已排除 `.env` 與 `artifacts/`。
- 僅供**你自己的帳號**每天一次使用。這是瀏覽器自動化，網站或 Cloudflare 政策改變時可能失效。與 Civitai 無關，風險自負。

## 授權

MIT，見 [LICENSE](LICENSE)。
