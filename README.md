# Civitai-Buzz

每天自動領取 Civitai 的 **25 Buzz**。

用你瀏覽器裡的 Cookie 登入，開啟 <https://civitai.red/>，點導覽列的 **Create**，
在彈出選單中按 **Claim 25 Buzz**，成功後結束。

結構沿用 [simao-silva/noip-renewer](https://github.com/simao-silva/noip-renewer)（MIT）：
無頭瀏覽器 + 一次性執行 + 明確退出碼，跑完就結束（`docker run --rm` 會自動移除容器）。

---

## 為什麼用 Cookie，而不是帳密

`civitai.red` 在 Cloudflare 後面。實測（headless 與非 headless 都試過）只會拿到
`Just a moment...` 的驗證頁，沒有任何登入表單可以操作。

真正能過去的東西是 `cf_clearance` 這張通行證，而它**綁定 IP + User-Agent**。
所以本專案直接把你瀏覽器裡那組 cookie 灌進無頭瀏覽器，並讓你指定同一組 UA。

> 結論：**請在產生 cookie 的同一台機器／同一個網路執行**，並讓 `USER_AGENT` 與該瀏覽器一致。

---

## 流程

1. 啟動 Chromium（可無頭），先灌入 cookie（含 `cf_clearance`）。
2. 開啟 <https://civitai.red/generate>；若仍是 Cloudflare 驗證頁，直接失敗並提示更新 cookie。
3. 關掉首次進入生成頁可能出現的導覽視窗（Skip / Close）。
4. 在頁面上找文字符合 `Claim 25 Buzz` 的按鈕並點擊。
5. 等出現 claimed／success 字樣或按鈕消失；若頁面本來就沒有可領項目，再退一步去開 Create 選單找。

> 若你的版面是把 `Claim 25 Buzz` 放在 Create 下拉選單裡，程式也會自動退回那條路徑
> （Create 是分裂按鈕：左邊跳 /create，右邊箭頭才開選單）。
> 找不到時會把選單內容印出來，方便判斷是「沒登入」還是「已領過」。

---

## 取得 Cookie

1. Chrome/Edge 開 <https://civitai.red/> 並確認已登入。
2. `F12` → **Network** → 重新整理 → 點任一 `civitai.red` 請求。
3. **Request Headers** → `Cookie` → 整段複製（會長這樣：`civitai-token=...; cf_clearance=...; ...`）。
4. 同時記下你的 **User-Agent**：同一頁的 Request Headers 裡就有。

---

## 快速開始

### A. Docker

```bash
docker build -t civitai-buzz .

docker run --rm \
  -e CIVITAI_COOKIE='civitai-token=...; cf_clearance=...' \
  -e USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...' \
  civitai-buzz
```

用 compose（推薦，設定寫在 `.env`）：

```bash
cp .env.example .env    # 貼上 CIVITAI_COOKIE 與 USER_AGENT
docker compose up --build
```

### B. Windows 本機（不用 Docker）

1. 安裝 Python 3.9+（勾 *Add python.exe to PATH*）。
2. **雙擊 `run.bat`**；第一次會建 `.venv` 並安裝 selenium。
3. 沒設定 cookie 時會問你，貼上整段即可。

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python buzz.py --cookie "civitai-token=...; cf_clearance=..."
```

成功時：

```
[15:20:01] Loaded 6 cookie(s): civitai-token, cf_clearance, ...
[15:20:07] Opened Create menu
[15:20:08] Clicking 'Claim 25 Buzz'
[15:20:09] Buzz claimed
[15:20:09] Done: +25 Buzz
```

---

## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `CIVITAI_COOKIE` | 必填 | 整段 Cookie header（含 `cf_clearance`） |
| `USER_AGENT` | Chrome 157 (Win64) | 必須與產生 cookie 的瀏覽器一致 |
| `CIVITAI_URL` | `https://civitai.red/generate` | 站台網址（給純網域會自動接 `/generate`） |
| `HEADLESS` | `true` | `false` 會開視窗（Cloudflare 較容易過） |
| `DEBUG` | `false` | 失敗時把截圖與 DOM 存到 `artifacts/` |
| `LOGIN_TIMEOUT` / `CLAIM_TIMEOUT` | 45 / 30 | 等頁面／等選單的秒數 |
| `BROWSER` | `chrome` | `chrome`（容器）或 `edge`（Windows） |

---

## 退出碼

| 代碼 | 意義 |
|---|---|
| `0` | 已領取，或今天已經領過 |
| `1` | 失敗：Cloudflare 擋住、找不到 Create／Claim、逾時 |
| `2` | 設定錯誤：沒有 cookie 或格式不對 |

---

## 排程（每天一次）

```cron
30 9 * * * cd /opt/civitai-buzz && /usr/bin/docker compose run --rm buzz >> buzz.log 2>&1
```

Windows 工作排程器：程式填 `run.bat`（要背景跑就把最後的 `pause` 拿掉）。

> `cf_clearance` 會過期（通常數小時到數天）。排程失敗時，重新抓一次 cookie 即可。

---

## 疑難排解

**一直停在 Cloudflare**
- `cf_clearance` 過期了 → 重新抓 cookie。
- UA 不一致 → `USER_AGENT` 必須與瀏覽器完全相同。
- IP 不一致 → 在別的網路／機器跑就會失效；請在同一台機器跑，或改用 `HEADLESS=false`。

**找不到 Create 按鈕**
代表頁面根本沒載入成功（還是驗證頁），或被導到登入頁。開 `DEBUG=true` 看 `artifacts/*.png`。

**選單裡沒有 Claim 25 Buzz**
程式會印出當下選單內容。若只有 Generate / Post Images / Upload a Model 之類，
代表 cookie 沒生效（未登入）——重新抓 cookie；若出現 `already claimed` 代表今天已領。

---

## 專案結構

```
.
├── buzz.py                  # 灌 cookie → 開 Create → Claim 25 Buzz
├── run.bat                  # Windows 一鍵執行
├── Dockerfile               # Debian + Chromium + chromedriver
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── .github/workflows/docker.yml
```

## 免責聲明

- 僅供**你自己的帳號**、每天一次使用。
- Cookie 等同帳號憑證，請勿外流；本專案只把它放進你本機的瀏覽器 session，不會上傳。
- 這是瀏覽器自動化，站方改版或 Cloudflare 政策變動就可能失效，風險自負。
- 與 Civitai 官方無任何關係。

## License

MIT，見 [LICENSE](LICENSE)。
