# Civitai-Buzz

每天自動領取 Civitai 的 **25 Buzz**。

用你瀏覽器裡的 Cookie 登入，開啟 <https://civitai.red/generate>，等 `Claim 25 Buzz`
出現就按下去，成功後結束。

## 參考來源與取捨

實作參考 Greasy Fork 的
[Civitai Auto-Clicker for Buzz and Follow](https://greasyfork.org/scripts/509803-civitai-auto-clicker-for-buzz-and-follow)
（MIT）。那個腳本的核心其實只有三行邏輯：

```js
Array.from(document.querySelectorAll('button'))
     .find(b => b.textContent.trim() === 'Claim 25 Buzz')
// 每秒輪詢 + MutationObserver，按鈕可見且未 disabled 就 click()
```

它另外附帶的東西我**沒有**移植，因為與「領取 Buzz」無關：

| 原腳本功能 | 處理 |
|---|---|
| `Follow` 三個頁面 | ❌ 移除 |
| `sessionStorage` 記錄已點次數 | ❌ 移除（每次執行本來就只領一次） |
| MutationObserver + 每秒輪詢 | ✅ 保留，改用 Selenium 輪詢 DOM |
| 「按鈕可見才點」的 `offsetParent` 判斷 | ✅ 保留（`getClientRects()`） |

## 流程

1. 啟動 Chromium（可無頭，也可用 Xvfb 開有頭），先灌入 cookie（含 `cf_clearance`）。
2. 開啟 <https://civitai.red/generate>；若仍是 Cloudflare 驗證頁，直接失敗並提示更新 cookie。
3. 每秒掃描一次 DOM，找文字等於 `Claim 25 Buzz` 的按鈕（找不到再用寬鬆比對，容納 `Claim 25,000 Buzz` 之類）。
4. 按鈕可見且未 disabled → 點擊。
5. 等按鈕消失或出現 claimed／success 字樣；若等了整個 `CLAIM_TIMEOUT` 都沒有按鈕，視為今日已領（exit 0）。

> 這個網站很晚才把按鈕掛上去，而且 headless 瀏覽器有時根本不會渲染它——所以有 `HEADLESS=false`（Xvfb）模式可切換。

## 取得 Cookie

1. Chrome/Edge 開 <https://civitai.red/> 並確認已登入。
2. `F12` → **Network** → 重新整理 → 點任一 `civitai.red` 請求。
3. **Request Headers** → `Cookie` → 整段複製（`__Secure-civ-token=...; __Secure-civ-device=...; ...`）。
4. 順手記下同一頁的 **User-Agent**。

> `cf_clearance` 綁 IP + User-Agent，若被 Cloudflare 擋住就要一起帶上，並讓 `USER_AGENT` 與瀏覽器一致。

## 快速開始

### A. Docker

```bash
docker build -t civitai-buzz .

docker run --rm \
  -e CIVITAI_COOKIE='__Secure-civ-token=...; __Secure-civ-device=...' \
  -e USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...' \
  civitai-buzz
```

用 compose（設定寫在 `.env`）：

```bash
cp .env.example .env
docker compose up --build
```

### B. Windows 本機（不用 Docker）

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python buzz.py --cookie "__Secure-civ-token=...; ..." --visible
```

或雙擊 `run.bat`（會問你貼 cookie）。

## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `CIVITAI_COOKIE` | 必填 | 整段 Cookie header |
| `USER_AGENT` | Chrome 157 (Win64) | 建議與產生 cookie 的瀏覽器一致 |
| `CIVITAI_URL` | `https://civitai.red/generate` | 給純網域會自動接 `/generate` |
| `HEADLESS` | `true` | `false` = Xvfb + 有頭 Chrome（最像真瀏覽器） |
| `CLAIM_TIMEOUT` | `300` | 等按鈕出現的秒數 |
| `CLAIM_TEXT` | `Claim 25 Buzz` | 按鈕精確文字 |
| `STRICT` | `false` | `true` = 等不到按鈕就 exit 1 |
| `DEBUG` | `false` | 失敗時存截圖與 DOM 到 `artifacts/` |

## 退出碼

| 代碼 | 意義 |
|---|---|
| `0` | 已領取，或今天已經領過 |
| `1` | 失敗：Cloudflare 擋住、cookie 失效、瀏覽器錯誤 |
| `2` | 設定錯誤：沒有 cookie 或格式不對 |

## 排程（每天一次）

```cron
30 9 * * * cd /opt/civitai-buzz && /usr/bin/docker compose run --rm buzz >> buzz.log 2>&1
```

Windows 工作排程器：程式填 `run.bat`（要背景跑就把最後的 `pause` 拿掉）。

> `__Secure-civ-token` 會過期（你的那組 exp 約一個月）。排程失敗時重抓 cookie 即可。

## 疑難排解

**一直停在 Cloudflare**
`cf_clearance` 過期或 UA 不一致 → 重抓 cookie、對齊 `USER_AGENT`，並在產生 cookie 的同一台機器／網路執行。

**等滿 300 秒都沒出現按鈕**
- 先確認帳號今天真的還沒領。
- 換 `HEADLESS=false`（Xvfb）再試——我實測 headless 模式整頁 DOM 完全沒有這個按鈕，有頭模式才可能出現。
- 開 `DEBUG=true`，把 `artifacts/*.png` 留下來看實際畫面。

**按鈕文字不同**
用 `CLAIM_TEXT` 覆蓋，例如 `-e CLAIM_TEXT='Claim 25 Buzz'`；寬鬆比對已涵蓋 `Claim 25,000 Buzz`。

## 專案結構

```
.
├── buzz.py                  # cookie → 開 /generate → 等按鈕 → 點擊
├── entrypoint.sh            # HEADLESS=false 時自動套 xvfb-run
├── run.bat                  # Windows 一鍵執行
├── Dockerfile               # Debian + Chromium + chromedriver + Xvfb
├── docker-compose.yml
└── .github/workflows/docker.yml
```

## 免責聲明

- 僅供**你自己的帳號**、每天一次使用。
- Cookie 等同帳號憑證，請勿外流。
- 這是瀏覽器自動化，站方改版或 Cloudflare 政策變動就可能失效，風險自負。
- 與 Civitai 官方無任何關係。

## License

MIT，見 [LICENSE](LICENSE)。輪詢邏輯參考 [Fontkodo 的 userscript](https://greasyfork.org/scripts/509803-civitai-auto-clicker-for-buzz-and-follow)（MIT）。
