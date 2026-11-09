# Civitai-Buzz

Automatically claim the daily **25 Buzz** at <https://civitai.red/generate>. The container starts, claims, and exits (process ends → container stops). No need to open a browser manually.

Modeled after [simao-silva/noip-renewer](https://github.com/simao-silva/noip-renewer): Docker + Selenium + credentials via environment variables + exit when done. The difference is the target site (Civitai) and the login method (browser cookie).

## How it works

The "Claim 25 Buzz" button is just the surface. The real action is the tRPC mutation `buzz.claimDailyBoostReward`, which is idempotent on the server side (repeated calls don't grant extra Buzz, so retries are safe).

Flow:

1. Inject cookies from `CIVITAI_COOKIE` (`.civitai.red` and `.civitai.com`).
2. Open `/generate` and wait for the Cloudflare challenge to pass on its own.
3. Call `user.userRewardDetails` and inspect `dailyBoost`:
   - `awarded > 0`: already claimed today, exit 0.
   - `awardedCount === 0`: `POST buzz.claimDailyBoostReward`.
4. Query again to confirm `awarded > 0` (waits up to `CLAIM_TIMEOUT` seconds); exit 0 on success.
5. If the API fails, fall back to clicking the "Claim 25 Buzz" button in the DOM, then verify via the API.

The container's main process is `buzz.py`, so it stops when the script ends; `restart: "no"` prevents automatic restarts.

> Unknowns: whether Cloudflare requires `cf_clearance` for datacenter IPs (VPS/cloud); if the site changes the tRPC names or payload, the API path will break (the DOM fallback is kept for this reason).

## Getting the Cookie and User-Agent

1. Log in at <https://civitai.red/> with Chrome or Edge.
2. `F12` → **Network** → refresh → click any `civitai.red` request → copy the full `Cookie` value from **Request Headers** (including `__Secure-civ-*`).
3. Run `navigator.userAgent` in the Console to get your User-Agent.

`__Secure-civ-token` expires after about a month; just grab a fresh one when it does.

## Quick start

### Docker (recommended)

```bash
docker build -t civitai-buzz .

docker run --rm \
  -e CIVITAI_COOKIE='<full Cookie>' \
  -e USER_AGENT='<your User-Agent>' \
  civitai-buzz
```

`--rm` deletes the container when it exits. To keep logs, drop `--rm` and use `docker logs`.

### Docker Compose

```bash
export CIVITAI_COOKIE='...'
export USER_AGENT='...'
docker compose up --build
```

Compose passes the shell variables straight through, so no `.env` file is needed in the project.

### Windows (without Docker)

Double-click `run.bat` and enter the cookie and User-Agent when prompted (press Enter to skip the latter). The first run creates `.venv` and installs dependencies automatically.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `CIVITAI_COOKIE` | **required** | Full Cookie header |
| `USER_AGENT` | empty | Empty = browser default; should match the browser that produced the cookie |
| `CIVITAI_URL` | `https://civitai.red/generate` | A bare domain gets `/generate` appended automatically |
| `HEADLESS` | `true` | `false` = Xvfb + headed Chrome (most browser-like) |
| `CF_TIMEOUT` | `90` | Seconds to wait for the Cloudflare challenge |
| `CLAIM_TIMEOUT` | `300` | Seconds to wait for the reward to be credited |
| `POLL_INTERVAL` | `1.0` | Polling interval (seconds) |
| `STRICT` | `false` | `true` = exit 1 if nothing was claimed |
| `DEBUG` | `false` | On failure, save screenshots and DOM to `artifacts/` |
| `RUN_TIMEOUT` | `900` | Hard limit inside the container to prevent hangs |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Claimed, or already claimed today |
| `1` | Failure: Cloudflare, invalid cookie, browser error |
| `2` | Configuration error: missing or malformed cookie |

Check status without claiming:

```bash
docker run --rm -e CIVITAI_COOKIE='...' -e USER_AGENT='...' civitai-buzz --check
```

## Daily schedule

Linux cron (keep the env file outside the project):

```cron
30 9 * * * docker run --rm --env-file /etc/civitai-buzz.env civitai-buzz >> /var/log/civitai-buzz.log 2>&1
```

Windows Task Scheduler: set the program to `run.bat` (remove the trailing `pause` for scheduled runs).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Stuck at Cloudflare | Re-grab the cookie, align `USER_AGENT`, and run on the same machine/network that produced the cookie; use `HEADLESS=false` if needed |
| `Cookie rejected (HTTP 401)` | `__Secure-civ-token` has expired; log in again and copy a new Cookie |
| `dailyBoost` missing | The account may not be eligible, or the site changed the type; exits 0 when `STRICT=false` |
| Both API and DOM fail | Set `DEBUG=true` and check `artifacts/`, or try `HEADLESS=false` |
| Verify the claim | The blue balance in `buzz.getBuzzAccount` goes up by 25 and `dailyBoost.awarded` becomes 25 |

## Project structure

```
.
├── buzz.py               # cookie → /generate → tRPC claim (DOM as fallback)
├── entrypoint.sh         # wraps Xvfb when HEADLESS=false; exits when done
├── run.bat               # one-click Windows runner
├── Dockerfile            # Debian + Chromium + chromedriver + Xvfb
├── docker-compose.yml
├── requirements.txt
└── .github/workflows/docker.yml
```

## Security and disclaimer

- Treat the cookie like a password, since it is equivalent to your account credentials. Pass it only via `-e` / shell environment variables; never write it into the Dockerfile, image, compose file, or git. The program does not print it to logs. `.gitignore` / `.dockerignore` already exclude `.env` and `artifacts/`.
- For use with **your own account only**, once per day. This is browser automation and may break if the site or Cloudflare policy changes. It is not affiliated with Civitai. Use at your own risk.

## License

MIT, see [LICENSE](LICENSE).
