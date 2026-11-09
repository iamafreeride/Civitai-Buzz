# Civitai-Buzz

**English** | [繁體中文](README.md)

Automatically claims the daily **25 Buzz** at <https://civitai.red/generate>. The container starts, claims, and exits. No need to open a browser. Modeled after [simao-silva/noip-renewer](https://github.com/simao-silva/noip-renewer): Docker + Selenium + credentials via environment variables + exit when done. Login uses your browser cookie.

## How it works

The "Claim 25 Buzz" button is just the surface; the real action is the tRPC mutation `buzz.claimDailyBoostReward`, which is idempotent on the server (repeated calls grant nothing extra, so retries are safe).

1. Inject cookies from `CIVITAI_COOKIE` (`.civitai.red` and `.civitai.com`).
2. Open `/generate` and wait for the Cloudflare challenge to pass.
3. Call `user.userRewardDetails` and check `dailyBoost`: `awarded > 0` means already claimed (exit 0); `awardedCount === 0` triggers `POST buzz.claimDailyBoostReward`.
4. Query again to confirm `awarded > 0` (up to `CLAIM_TIMEOUT` seconds), then exit 0.
5. If the API fails, fall back to clicking the "Claim 25 Buzz" button in the DOM and verify via the API.

> Unknowns: whether Cloudflare requires `cf_clearance` for datacenter IPs (VPS/cloud), and whether the site renames the tRPC calls or changes the payload (the DOM fallback exists for this).

## Getting the Cookie and User-Agent

1. Log in at <https://civitai.red/> with Chrome or Edge.
2. `F12` → **Network** → refresh → click any `civitai.red` request → copy the full `Cookie` value from **Request Headers** (including `__Secure-civ-*`).
3. Run `navigator.userAgent` in the Console to get your User-Agent.

`__Secure-civ-token` expires after about a month; grab a fresh cookie when it does.

## Quick start

### Docker (recommended)

```bash
docker build -t civitai-buzz .

docker run --rm \
  -e CIVITAI_COOKIE='<full Cookie>' \
  -e USER_AGENT='<your User-Agent>' \
  civitai-buzz
```

Drop `--rm` if you want to keep logs (`docker logs`).

### Docker Compose

```bash
export CIVITAI_COOKIE='...'
export USER_AGENT='...'
docker compose up --build
```

Compose passes the shell variables through, so no `.env` file is needed.

### Windows (no Docker)

Double-click `run.bat` and enter the cookie and User-Agent when prompted (Enter skips the latter). The first run creates `.venv` and installs dependencies.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `CIVITAI_COOKIE` | **required** | Full Cookie header |
| `USER_AGENT` | empty | Empty = browser default; should match the browser that produced the cookie |
| `CIVITAI_URL` | `https://civitai.red/generate` | A bare domain gets `/generate` appended |
| `HEADLESS` | `true` | `false` = Xvfb + headed Chrome (most browser-like) |
| `CF_TIMEOUT` | `90` | Seconds to wait for the Cloudflare challenge |
| `CLAIM_TIMEOUT` | `300` | Seconds to wait for the reward to be credited |
| `POLL_INTERVAL` | `1.0` | Polling interval (seconds) |
| `STRICT` | `false` | `true` = exit 1 if nothing was claimed |
| `DEBUG` | `false` | Save screenshots and DOM to `artifacts/` on failure |
| `RUN_TIMEOUT` | `900` | Hard limit inside the container to prevent hangs |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Claimed, or already claimed today |
| `1` | Failure: Cloudflare, invalid cookie, browser error |
| `2` | Configuration error: cookie missing or malformed |

Check status without claiming:

```bash
docker run --rm -e CIVITAI_COOKIE='...' -e USER_AGENT='...' civitai-buzz --check
```

## Daily schedule

Linux cron (keep the env file outside the project):

```cron
30 9 * * * docker run --rm --env-file /etc/civitai-buzz.env civitai-buzz >> /var/log/civitai-buzz.log 2>&1
```

Windows Task Scheduler: run `run.bat` (remove the trailing `pause`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Stuck at Cloudflare | Re-grab the cookie, align `USER_AGENT`, run on the same machine/network that produced the cookie; use `HEADLESS=false` if needed |
| `Cookie rejected (HTTP 401)` | `__Secure-civ-token` expired; log in again and copy a new Cookie |
| `dailyBoost` missing | Account may be ineligible or the site changed the type; exits 0 when `STRICT=false` |
| Both API and DOM fail | Set `DEBUG=true` and check `artifacts/`, or try `HEADLESS=false` |
| Verify the claim | Blue balance in `buzz.getBuzzAccount` rises by 25 and `dailyBoost.awarded` becomes 25 |

## Project structure

```
buzz.py               cookie → /generate → tRPC claim (DOM fallback)
entrypoint.sh         wraps Xvfb when HEADLESS=false; exits when done
run.bat               Windows one-click runner
Dockerfile            Debian + Chromium + chromedriver + Xvfb
docker-compose.yml
requirements.txt
.github/workflows/docker.yml
```

## Security and disclaimer

- Treat the cookie like a password. Pass it only via `-e` / shell environment variables; never put it in the Dockerfile, image, compose file, or git. The program does not log it, and `.gitignore` / `.dockerignore` already exclude `.env` and `artifacts/`.
- For **your own account only**, once a day. This is browser automation and may break if the site or Cloudflare policy changes. Not affiliated with Civitai. Use at your own risk.

## License

MIT, see [LICENSE](LICENSE).
