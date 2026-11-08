# Civitai-Buzz

每天在 <https://civitai.red/generate> 領取 **25 Buzz**。容器啟動後自動領取，領到就結束
（進程結束 → 容器停止），不需要手動開瀏覽器。

本專案是參考 [simao-silva/noip-renewer](https://github.com/simao-silva/noip-renewer)
（[Docker Hub](https://hub.docker.com/r/simaofsilva/noip-renewer)）的作法改寫：
一樣是「Docker + Selenium + 環境變數憑證 + 跑完就退出」，只是把目標網站從 NOIP
換成 Civitai 的 `/generate`，登入方式從帳密改成瀏覽器 Cookie。

---

## 1. 分析：`/generate` 的「Claim 25 Buzz」實際怎麼運作

> 分析方式：**執行期觀察**（真實瀏覽器的 DOM 與網路流量）＋ **前端 bundle 靜態檢視**。
> 下面每條都標明是「觀察」還是「推論」。

### 1.1 觀察到的證據

| # | 證據 | 類型 |
|---|---|---|
| 1 | 用 `requests` 直接 `GET https://civitai.red/generate` → **HTTP 403 `<title>Just a moment...</title>`** | 觀察 |
| 2 | 同一台機器改用 headless Chrome（帶 cookie）→ **HTTP 200，標題 `Generate`**，Cloudflare JS 挑戰自行通過 | 觀察 |
| 3 | `GET /api/trpc/user.userRewardDetails?input={"json":{"authed":true}}` 回傳 11 種獎勵，其中 `type: "dailyBoost"`：`awardAmount: 25`、`cap: 25`、`triggerDescription: "By claiming it daily in the Image generator"` | 觀察 |
| 4 | `POST /api/trpc/buzz.claimDailyBoostReward`，body `{"json":null}` → **HTTP 200**，`{"result":{"data":{"json":null}}}` | 觀察 |
| 5 | 領取後 `buzz.getBuzzAccount` 的 blue buzz **2,285 → 2,310（+25）**，`dailyBoost.awarded=25, awardedCount=1` | 觀察 |
| 6 | 再打一次同一個 POST → 仍 HTTP 200，但不會重複加點（伺服器端冪等） | 觀察 |
| 7 | 前端 chunk `2m1r7m9d4s70g.js` 內：按鈕只在 `canShow = 已登入 && !loading && account.charge && dailyBoost && awardedCount === 0` 時渲染，文字是 `Claim ${awardAmount} Buzz` | 觀察 |

### 1.2 推論

- **按鈕只是表層。** 真正的領取動作是 tRPC mutation `buzz.claimDailyBoostReward`；
  按鈕沒出現不代表當天不能領，可能只是 React 還沒掛載、被 tour／popover 蓋住，
  或 headless 根本沒渲染。直接打 API 不受這些影響。
- **伺服器端冪等。** 重複呼叫不會重複給點，所以重試是安全的。
- **判斷「今天領過沒」要看 `dailyBoost.awarded` / `awardedCount`**，不是看按鈕在不在。

### 1.3 未知

- Cloudflare 對資料中心 IP（VPS／雲端 Docker）是否要求 `cf_clearance`，本機測試無法代表。
- 站方日後若改 tRPC 名稱或 payload 形狀，API 路徑會失效——程式已保留 DOM 點擊的退路。

---

## 2. 流程

1. 用 `CIVITAI_COOKIE` 灌入 cookie（`.civitai.red` 與 `.civitai.com`）。
2. 開 `https://civitai.red/generate`，等 Cloudflare 的 JS 挑戰自己通過。
3. 呼叫 `user.userRewardDetails`，確認登入狀態並找 `dailyBoost`：
   - `awarded > 0` → 今天已領，**exit 0**（容器結束）。
   - `awardedCount === 0` → `POST buzz.claimDailyBoostReward`。
4. 重新查詢確認 `awarded > 0`（最多等 `CLAIM_TIMEOUT` 秒），成功 → **exit 0**。
5. 若 API 失敗，退回原本「找 `Claim 25 Buzz` 按鈕來點」的方式，再用 API 驗證。
6. 進程結束 → 容器停止；搭配 `docker run --rm` 會自動移除容器。

> 「領取成功後關閉容器」不需要特製指令：容器的主進程就是 `buzz.py`，
> 它一結束容器就停。`restart: "no"` 確保它不會被自動重啟。

---

## 3. 取得 Cookie 與 User-Agent

1. Chrome／Edge 開 <https://civitai.red/> 並確認已登入。
2. `F12` → **Network** → 重新整理 → 點任一 `civitai.red` 請求。
3. **Request Headers** → `Cookie` → 整段複製（包含登入用的 `__Secure-civ-*` 欄位）。
4. 同一頁記下 **User-Agent**（`F12` → Console → `navigator.userAgent`）。

> 登入用的 `__Secure-civ-token` 是 JWT，會過期（約一個月）。過期後重新抓一次即可。
> Cookie 等同帳號憑證，**只放在執行時的環境變數**，不要寫進任何檔案或提交。

---

## 4. 快速開始

### A. Docker（建議）

```bash
docker build -t civitai-buzz .

docker run --rm \
  -e CIVITAI_COOKIE='<整段 Cookie>' \
  -e USER_AGENT='<你的 User-Agent>' \
  civitai-buzz
```

`--rm`：容器結束後自動刪除。想保留日誌就別加 `--rm`，之後用 `docker logs civitai-buzz`。

### B. Docker Compose

```bash
export CIVITAI_COOKIE='...'
export USER_AGENT='...'
docker compose up --build
```

PowerShell：

```powershell
$env:CIVITAI_COOKIE='...'
$env:USER_AGENT='...'
docker compose up --build
```

compose 直接把 shell 的變數傳進容器，**不需要**在專案裡放 `.env`。
若你真的想用檔案，請放在專案外，例如
`docker run --rm --env-file /etc/civitai-buzz.env civitai-buzz`。

### C. Windows 本機（不用 Docker）

雙擊 `run.bat`，它會依序問 cookie 和 User-Agent（直接 Enter 可跳過後者），
第一次執行會自動建立 `.venv` 並安裝 selenium。

或手動：

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python buzz.py --cookie "..." 
```

---

## 5. 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `CIVITAI_COOKIE` | **必填** | 整段 Cookie header；只從環境讀取 |
| `USER_AGENT` | 空 | 空 = 用瀏覽器自己的 UA；建議填與產生 cookie 的瀏覽器一致 |
| `CIVITAI_URL` | `https://civitai.red/generate` | 給純網域會自動接 `/generate` |
| `HEADLESS` | `true` | `false` = Xvfb + 有頭 Chrome（最像真瀏覽器） |
| `CF_TIMEOUT` | `90` | 等 Cloudflare 挑戰通過的秒數 |
| `CLAIM_TIMEOUT` | `300` | 等獎勵入帳／按鈕出現的秒數 |
| `POLL_INTERVAL` | `1.0` | 輪詢間隔秒數 |
| `STRICT` | `false` | `true` = 沒領到就 exit 1 |
| `DEBUG` | `false` | 失敗時把截圖與 DOM 存到 `artifacts/` |
| `RUN_TIMEOUT` | `900` | 容器內的硬性上限，避免卡死 |

---

## 6. 退出碼與容器行為

| 代碼 | 意義 | 容器 |
|---|---|---|
| `0` | 已領取，或今天已經領過 | 正常停止（`--rm` 會刪除） |
| `1` | 失敗：Cloudflare、cookie 失效、瀏覽器錯誤 | 停止，可用 `docker logs` 查 |
| `2` | 設定錯誤：沒有 cookie、cookie 格式不對 | 停止 |

驗證目前狀態（不領取）：

```bash
docker run --rm -e CIVITAI_COOKIE='...' -e USER_AGENT='...' civitai-buzz --check
```

---

## 7. 排程（每天一次）

Linux cron（環境檔放專案外）：

```cron
30 9 * * * docker run --rm --env-file /etc/civitai-buzz.env civitai-buzz >> /var/log/civitai-buzz.log 2>&1
```

Windows 工作排程器：程式填 `run.bat`（排程用請把最後的 `pause` 拿掉）。

---

## 8. 疑難排解

**一直停在 Cloudflare**
`cf_clearance` 過期或 UA 不一致 → 重抓 cookie、對齊 `USER_AGENT`，
並在產生 cookie 的同一台機器／網路執行；必要時用 `HEADLESS=false`（Xvfb）。

**`Cookie rejected (HTTP 401)`**
`__Secure-civ-token` 過期了，重新登入並複製新的 Cookie。

**`dailyBoost` 不見了**
帳號可能不適用這個獎勵，或站方改了獎勵型別。`STRICT=false` 時會 exit 0。

**API 失敗、退回 DOM 也找不到按鈕**
開 `DEBUG=true`，看 `artifacts/*.png` 與 `*.html`；或用 `HEADLESS=false` 再試。

**確認真的領到了**
`buzz.getBuzzAccount` 的 blue 餘額應該 +25；`dailyBoost.awarded` 會變成 25。

---

## 9. 專案結構

```
.
├── buzz.py               # cookie → 開 /generate → tRPC 領取（DOM 點擊為退路）
├── entrypoint.sh         # HEADLESS=false 時套 Xvfb；跑完即退出
├── run.bat               # Windows 一鍵執行（詢問 cookie）
├── Dockerfile            # Debian + Chromium + chromedriver + Xvfb
├── docker-compose.yml    # 從 shell 傳入 secrets
├── requirements.txt
└── .github/workflows/docker.yml
```

---

## 10. 安全

- `CIVITAI_COOKIE`／`USER_AGENT` **不在** Dockerfile、image、compose 檔或 git 歷史中，
  只能由 `-e`／shell 環境變數傳入；程式也不會把它們印進日誌。
- `.dockerignore` 與 `.gitignore` 都排除了 `.env`、`artifacts/`、截圖與 DOM dump。
- 建議把 cookie 視為密碼：只用於自己的帳號、每天一次，外流等於帳號被接管。

## 11. 免責聲明

僅供**你自己的帳號**、每天一次使用。這是瀏覽器自動化，站方改版或 Cloudflare
政策變動就可能失效；與 Civitai 官方無任何關係，風險自負。

## License

MIT，見 [LICENSE](LICENSE)。
