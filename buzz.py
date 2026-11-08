#!/usr/bin/env python3
"""
Civitai-Buzz
============

每天在 https://civitai.red/generate 領取 25 Buzz；領到就結束，容器也跟著結束。

為什麼不是「找按鈕來點」？
--------------------------
對 civitai.red/generate 做過一輪觀察（瀏覽器實際跑 + 前端 bundle 靜態檢視）後，
確認那顆 `Claim 25 Buzz` 按鈕只是表層，真正的動作出現在 tRPC：

    GET  /api/trpc/user.userRewardDetails        -> 找到 type == "dailyBoost"
    POST /api/trpc/buzz.claimDailyBoostReward    -> 領取（回傳 null）

前端邏輯（chunk 內）：只有 `dailyBoost.awardedCount === 0`、且 buzz account 有
charge 時才把按鈕畫出來，文字是 `Claim ${awardAmount} Buzz`。也就是說：

  * 按鈕不存在 != 沒有獎勵，可能只是還沒渲染、被 tour 蓋住、或 headless 沒畫。
  * 直接打 tRPC 不受 DOM/React/overlay 影響，速度快很多，也更好驗證。

所以本程式先走 API，失敗才退回「找按鈕來點」的舊做法。

安全
----
`CIVITAI_COOKIE` 與 `USER_AGENT` 只從環境變數讀取，不寫入檔案、不進 image、
不留 log。請用 `docker run -e ...` 或 shell 環境變數傳入。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
    JavascriptException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

SITE_URL = os.getenv("CIVITAI_URL", "https://civitai.red/generate").rstrip("/")
if SITE_URL.count("/") == 2:  # bare origin -> the generate page
    SITE_URL = SITE_URL + "/generate"

#: Empty means "let the browser send its own UA". There is deliberately no
#: baked-in UA here: USER_AGENT must be supplied at runtime, never stored.
COOKIE_RAW = os.getenv("CIVITAI_COOKIE", "")
USER_AGENT = os.getenv("USER_AGENT", "").strip()

BROWSER = os.getenv("BROWSER", "chrome").strip().lower()
HEADLESS = os.getenv("HEADLESS", "true").strip().lower() not in {"0", "false", "no"}
DEBUG = os.getenv("DEBUG", "false").strip().lower() in {"1", "true", "yes"}
#: When nothing can be claimed, exit 1 instead of "nothing to do".
STRICT = os.getenv("STRICT", "false").strip().lower() in {"1", "true", "yes"}

#: Cloudflare's non-interactive challenge needs a few seconds in a real browser.
CF_TIMEOUT = float(os.getenv("CF_TIMEOUT", "90"))
#: How long to keep polling for the reward to show up as awarded.
CLAIM_TIMEOUT = float(os.getenv("CLAIM_TIMEOUT", "300"))
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))

ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "/app/artifacts"))

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_CONFIG = 2

#: Exact label first, then a tolerant form for locales/amounts.
CLAIM_TEXT = os.getenv("CLAIM_TEXT", "Claim 25 Buzz")
CLAIM_RE = re.compile(r"claim\s*[\d,]*\s*buzz", re.I)

#: tRPC procedures (observed on /generate, see module docstring).
PROC_REWARDS = "user.userRewardDetails"
PROC_CLAIM = "buzz.claimDailyBoostReward"
PROC_ACCOUNT = "buzz.getBuzzAccount"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def log(message: str) -> None:
    text = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, "replace").decode(encoding, "replace"), flush=True)


def norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def visible(driver, element) -> bool:
    """Same idea as the userscript's `offsetParent !== null`."""
    try:
        return driver.execute_script(
            "return !!(arguments[0].offsetWidth || arguments[0].offsetHeight "
            "|| arguments[0].getClientRects().length);",
            element,
        )
    except (JavascriptException, StaleElementReferenceException, WebDriverException):
        return False


def click(driver, element) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    except (JavascriptException, StaleElementReferenceException):
        pass
    try:
        element.click()
        return True
    except (ElementClickInterceptedException, ElementNotInteractableException):
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except (JavascriptException, StaleElementReferenceException):
            return False
    except (StaleElementReferenceException, WebDriverException):
        return False


def save_artifacts(driver, tag: str) -> None:
    try:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        driver.save_screenshot(str(ARTIFACTS_DIR / f"{stamp}-{tag}.png"))
        (ARTIFACTS_DIR / f"{stamp}-{tag}.html").write_text(driver.page_source, encoding="utf-8")
        log(f"Debug artifacts written to {ARTIFACTS_DIR}")
    except Exception as exc:
        log(f"Could not write artifacts: {exc}")


def page_text(driver) -> str:
    try:
        return driver.find_element(By.TAG_NAME, "body").text
    except WebDriverException:
        return ""


# --------------------------------------------------------------------------- #
# Cookies
# --------------------------------------------------------------------------- #


def parse_cookie_header(raw: str) -> list[tuple[str, str]]:
    text = raw.strip()
    if text.lower().startswith("cookie:"):
        text = text[7:]
    pairs = []
    for part in text.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        if name.strip():
            pairs.append((name.strip(), value.strip().strip('"')))
    return pairs


def install_cookies(driver, pairs: list[tuple[str, str]]) -> int:
    installed = 0
    for name, value in pairs:
        for domain in (".civitai.red", ".civitai.com"):
            try:
                driver.execute_cdp_cmd(
                    "Network.setCookie",
                    {
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": "/",
                        "secure": True,
                        "httpOnly": False,
                    },
                )
                installed += 1
            except WebDriverException:
                continue
    return installed


# --------------------------------------------------------------------------- #
# tRPC (runs inside the page, so Cloudflare cookies + same-origin apply)
# --------------------------------------------------------------------------- #


class CookieRejected(Exception):
    """The page accepted the session but the API says we are not logged in."""


def _trpc_get(driver, procedure: str) -> dict:
    return driver.execute_async_script(
        """
        const proc = arguments[0], done = arguments[arguments.length - 1];
        const url = '/api/trpc/' + proc + '?input=' +
            encodeURIComponent(JSON.stringify({ json: { authed: true } }));
        fetch(url, { credentials: 'include', headers: { accept: 'application/json' } })
          .then(async (r) => done({ status: r.status, body: await r.text() }))
          .catch((e) => done({ status: 0, body: String(e) }));
        """,
        procedure,
    )


def _trpc_post(driver, procedure: str, payload=None) -> dict:
    return driver.execute_async_script(
        """
        const proc = arguments[0], body = arguments[1];
        const done = arguments[arguments.length - 1];
        fetch('/api/trpc/' + proc, {
          method: 'POST',
          credentials: 'include',
          headers: { 'content-type': 'application/json', accept: 'application/json' },
          body: JSON.stringify({ json: body }),
        })
          .then(async (r) => done({ status: r.status, body: await r.text() }))
          .catch((e) => done({ status: 0, body: String(e) }));
        """,
        procedure,
        payload,
    )


def _decode(response: dict) -> object:
    """Unwrap a tRPC envelope: result.data.json (or raise with the error text)."""
    if not response or not response.get("status"):
        raise WebDriverException(f"tRPC request failed: {response}")
    status = response["status"]
    body = response.get("body") or ""
    if status in (401, 403):
        raise CookieRejected(f"HTTP {status}: session is not authenticated")
    try:
        payload = json.loads(body)
    except ValueError:
        raise WebDriverException(f"tRPC returned HTTP {status}: {body[:200]}")
    if isinstance(payload, dict) and payload.get("error"):
        err = payload["error"]
        message = (err.get("json") or {}).get("message") or str(err)
        raise WebDriverException(f"tRPC error: {message}")
    return ((payload.get("result") or {}).get("data") or {}).get("json")


def fetch_rewards(driver) -> list[dict]:
    data = _decode(_trpc_get(driver, PROC_REWARDS))
    if not isinstance(data, list):
        raise WebDriverException(f"Unexpected userRewardDetails payload: {data!r}")
    return data


def fetch_balance(driver) -> dict:
    try:
        data = _decode(_trpc_get(driver, PROC_ACCOUNT))
        return data if isinstance(data, dict) else {}
    except (WebDriverException, CookieRejected):
        return {}


def daily_boost(rewards: list[dict]) -> dict | None:
    return next((r for r in rewards if r.get("type") == "dailyBoost"), None)


def is_awarded(boost: dict | None) -> bool:
    if not boost:
        return False
    return int(boost.get("awarded") or 0) > 0 or int(boost.get("awardedCount") or 0) > 0


# --------------------------------------------------------------------------- #
# Browser
# --------------------------------------------------------------------------- #


def safe_quit(driver, timeout: float = 15.0) -> None:
    """driver.quit() can block forever in a container; never let it hold us."""

    def _quit():
        try:
            driver.quit()
        except Exception:
            pass

    thread = threading.Thread(target=_quit, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        log("Browser did not shut down cleanly; exiting anyway")


def build_driver():
    driver_path = os.getenv("WEBDRIVER_PATH")
    if not driver_path:
        for candidate in (
            "/usr/bin/chromedriver",
            "/usr/lib/chromium/chromedriver",
            "/usr/bin/msedgedriver",
        ):
            if Path(candidate).exists():
                driver_path = candidate
                break

    args = [
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--window-size=1440,900",
        "--lang=en-US",
        "--disable-blink-features=AutomationControlled",
        "--use-gl=angle",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--ignore-gpu-blocklist",
        # headed-in-container hygiene: no first-run dialogs, no background sync
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-features=Translate,MediaRouter",
        "--metrics-recording-only",
        "--mute-audio",
    ]
    # Only override the UA when the operator supplied one. Never ship a literal.
    if USER_AGENT:
        args.append(f"--user-agent={USER_AGENT}")
    if HEADLESS:
        args.insert(0, "--headless=new")

    if BROWSER in {"edge", "msedge"}:
        from selenium.webdriver.edge.options import Options as EdgeOptions
        from selenium.webdriver.edge.service import Service as EdgeService

        options = EdgeOptions()
        for argument in args:
            options.add_argument(argument)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        service = EdgeService(executable_path=driver_path) if driver_path else EdgeService()
        log(f"Starting Edge ({'headless' if HEADLESS else 'visible'})")
        driver = webdriver.Edge(options=options, service=service)
    else:
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service as ChromeService

        options = ChromeOptions()
        for argument in args:
            options.add_argument(argument)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        service = ChromeService(executable_path=driver_path) if driver_path else ChromeService()
        log(f"Starting Chrome ({'headless' if HEADLESS else 'visible'})")
        driver = webdriver.Chrome(options=options, service=service)

    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
        )
    except WebDriverException:
        pass
    return driver


def wait_for_cloudflare(driver, timeout: float) -> bool:
    """Cloudflare's challenge is JS-driven; give the browser time to clear it."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        title = (driver.title or "").lower()
        if "just a moment" not in title and "attention required" not in title:
            text = page_text(driver)[:600].lower()
            if "verifying you are human" not in text and "enable javascript and cookies" not in text:
                return True
        time.sleep(1)
    return False


# --------------------------------------------------------------------------- #
# Claim paths
# --------------------------------------------------------------------------- #


def claim_via_api(driver) -> str:
    """Returns claimed | already | no-reward | failed."""
    rewards = fetch_rewards(driver)
    boost = daily_boost(rewards)
    if boost is None:
        log("userRewardDetails has no 'dailyBoost' entry")
        return "no-reward"

    log(
        "dailyBoost: awardAmount={} awarded={} awardedCount={}".format(
            boost.get("awardAmount"), boost.get("awarded"), boost.get("awardedCount")
        )
    )
    if is_awarded(boost):
        return "already"

    before = fetch_balance(driver)
    log(f"Buzz balance before: {before or 'unknown'}")

    response = _trpc_post(driver, PROC_CLAIM, payload=None)
    log(f"claimDailyBoostReward -> HTTP {response.get('status')} {str(response.get('body'))[:160]}")

    deadline = time.time() + min(CLAIM_TIMEOUT, 60)
    while time.time() < deadline:
        try:
            if is_awarded(daily_boost(fetch_rewards(driver))):
                after = fetch_balance(driver)
                log(f"Buzz balance after: {after or 'unknown'}")
                return "claimed"
        except WebDriverException as exc:
            log(f"Verification query failed: {exc}")
        time.sleep(POLL_INTERVAL)
    return "failed"


# ---- DOM fallback: the original userscript behaviour ----------------------- #

FIND_JS = """
const exact = arguments[0];
const re = arguments[1];
const buttons = Array.from(document.querySelectorAll('button'));
let match = buttons.find(b => (b.textContent || '').trim() === exact);
if (!match) {
    const rx = new RegExp(re, 'i');
    match = buttons.find(b => rx.test((b.textContent || '').trim())
                          || rx.test(b.getAttribute('aria-label') || ''));
}
if (!match) return '';
match.setAttribute('data-civitai-claim', '1');
return (match.textContent || '').trim();
"""


def find_claim_button(driver):
    try:
        label = driver.execute_script(FIND_JS, CLAIM_TEXT, CLAIM_RE.pattern)
    except (JavascriptException, WebDriverException):
        return None
    if not label:
        return None
    try:
        return driver.find_element(By.CSS_SELECTOR, "[data-civitai-claim='1']")
    except (NoSuchElementException, WebDriverException):
        return None


def dismiss_tour(driver) -> None:
    """The /generate first-visit tour covers the left panel on a fresh profile."""
    try:
        buttons = driver.find_elements(By.CSS_SELECTOR, "button")
    except WebDriverException:
        return

    for element in buttons:
        try:
            if not visible(driver, element):
                continue
            label = norm(element.text).lower()
            if label in {"skip", "close", "close ad", "dismiss", "got it", "no thanks"}:
                if click(driver, element):
                    log(f"Dismissed overlay ({label})")
                    time.sleep(1.0)
                    return
        except (StaleElementReferenceException, WebDriverException):
            continue


def claim_via_dom(driver) -> str:
    """Poll for the button, click it once, then confirm through the API."""
    deadline = time.time() + CLAIM_TIMEOUT
    tries = 0

    while time.time() < deadline:
        tries += 1
        if tries % 20 == 1:
            dismiss_tour(driver)

        button = find_claim_button(driver)
        if button is not None and visible(driver, button) and button.is_enabled():
            log(f"Clicking '{CLAIM_TEXT}'")
            if not click(driver, button):
                log("Click was blocked, retrying")
                time.sleep(POLL_INTERVAL)
                continue

            confirm_deadline = time.time() + 30
            while time.time() < confirm_deadline:
                try:
                    if is_awarded(daily_boost(fetch_rewards(driver))):
                        return "claimed"
                except (WebDriverException, CookieRejected):
                    pass
                if find_claim_button(driver) is None:
                    return "claimed"
                time.sleep(POLL_INTERVAL)
            return "clicked"

        try:
            if is_awarded(daily_boost(fetch_rewards(driver))):
                return "already"
        except (WebDriverException, CookieRejected):
            pass
        time.sleep(POLL_INTERVAL)

    return "none"


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def get_cookie(args) -> str:
    raw = (args.cookie or COOKIE_RAW or "").strip()
    if not raw and sys.stdin is not None and sys.stdin.isatty():
        raw = input("Cookie (paste the whole 'name=value; ...' string): ").strip()
    if not raw:
        raise SystemExit(
            "Missing cookie.\n"
            "  Docker : docker run --rm -e CIVITAI_COOKIE='a=b; c=d' -e USER_AGENT='...' civitai-buzz\n"
            "  Local  : python buzz.py --cookie 'a=b; c=d'\n"
            "  Where  : DevTools -> Network -> any request -> Request Headers -> Cookie"
        )
    if "=" not in raw:
        raise SystemExit("That does not look like a cookie string (expected 'name=value; ...')")
    return raw


def main(argv: list[str] | None = None) -> int:
    global DEBUG, HEADLESS

    parser = argparse.ArgumentParser(description="Claim the daily 25 Buzz on Civitai")
    parser.add_argument("--cookie", help="full cookie header value")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--visible", action="store_true", help="show the browser window")
    parser.add_argument("--check", action="store_true", help="report state without claiming")
    parser.add_argument("--timeout", type=float, help="seconds to wait for the claim")
    args = parser.parse_args(argv or sys.argv[1:])

    DEBUG = DEBUG or args.debug
    if args.visible:
        HEADLESS = False
    if args.timeout:
        globals()["CLAIM_TIMEOUT"] = args.timeout

    try:
        raw_cookie = get_cookie(args)
    except SystemExit as exc:
        log(str(exc))
        return EXIT_CONFIG

    pairs = parse_cookie_header(raw_cookie)
    if not pairs:
        log("No usable cookies parsed")
        return EXIT_CONFIG
    log(f"Loaded {len(pairs)} cookie(s)")

    driver = None
    try:
        driver = build_driver()
        driver.set_page_load_timeout(90)
        driver.set_script_timeout(90)
        log(f"Installed {install_cookies(driver, pairs)} cookie entries")

        driver.get(SITE_URL)
        log("Waiting for Cloudflare / app boot")
        if not wait_for_cloudflare(driver, CF_TIMEOUT):
            log("Cloudflare is still challenging this session (refresh the cookie / user-agent)")
            save_artifacts(driver, "cloudflare")
            return EXIT_FAIL
        log(f"Page ready: {driver.title!r}")

        # Confirm the session before doing anything else.
        try:
            fetch_rewards(driver)
        except CookieRejected as exc:
            log(f"Cookie rejected ({exc}). Log in again and copy a fresh Cookie header.")
            save_artifacts(driver, "cookie-rejected")
            return EXIT_FAIL

        if args.check:
            boost = daily_boost(fetch_rewards(driver))
            log(f"dailyBoost: {json.dumps(boost, ensure_ascii=False) if boost else 'missing'}")
            log(f"Buzz balance: {fetch_balance(driver)}")
            return EXIT_OK

        result = "failed"
        try:
            result = claim_via_api(driver)
        except CookieRejected as exc:
            log(f"Cookie rejected ({exc})")
            save_artifacts(driver, "cookie-rejected")
            return EXIT_FAIL
        except WebDriverException as exc:
            log(f"API claim failed ({exc}); falling back to the button")

        if result in {"already", "claimed"}:
            if result == "already":
                log("Nothing to do: today's 25 Buzz was already claimed")
            else:
                log("Done: +25 Buzz")
            return EXIT_OK

        log("Falling back to DOM click")
        result = claim_via_dom(driver)

        if result in {"claimed", "clicked"}:
            log("Done: +25 Buzz" if result == "claimed" else "Clicked, but could not verify the award")
            return EXIT_OK if result == "claimed" else EXIT_FAIL
        if result == "already":
            log("Nothing to do: today's 25 Buzz was already claimed")
            return EXIT_OK

        log(
            "No claim was possible: the reward entry is missing, already claimed, or "
            "this account is not eligible. Set STRICT=true to treat it as a failure."
        )
        save_artifacts(driver, "claim-failed")
        return EXIT_FAIL if STRICT else EXIT_OK

    except TimeoutException as exc:
        log(f"Timed out: {exc}")
        if driver is not None:
            save_artifacts(driver, "timeout")
        return EXIT_FAIL
    except WebDriverException as exc:
        log(f"Browser error: {getattr(exc, 'msg', exc)}")
        if driver is not None:
            save_artifacts(driver, "browser-error")
        return EXIT_FAIL
    finally:
        if driver is not None:
            safe_quit(driver)


if __name__ == "__main__":
    sys.exit(main())
