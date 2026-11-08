#!/usr/bin/env python3
"""
Civitai-Buzz
============

每天領取 Civitai 的 25 Buzz。

做法參考 Greasy Fork 上的「Civitai Auto-Clicker for Buzz and Follow」：
那個腳本其實只做一件事——持續輪詢頁面，等文字為 `Claim 25 Buzz` 的按鈕出現、
可見且未被停用時按下去。它附帶的「Follow 三個頁面」與本專案無關，已移除。

本專案因此只負責：
  1. 用你的 Cookie 登入（這個站台在 Cloudflare 後面，沒有帳密表單）
  2. 開啟 https://civitai.red/generate
  3. 等 `Claim 25 Buzz` 出現並點擊
  4. 確認結果後結束
"""

from __future__ import annotations

import argparse
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

COOKIE_RAW = os.getenv("CIVITAI_COOKIE", "")
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
)

BROWSER = os.getenv("BROWSER", "chrome").strip().lower()
HEADLESS = os.getenv("HEADLESS", "true").strip().lower() not in {"0", "false", "no"}
DEBUG = os.getenv("DEBUG", "false").strip().lower() in {"1", "true", "yes"}
#: When the button never shows up, exit 1 instead of "nothing to claim".
STRICT = os.getenv("STRICT", "false").strip().lower() in {"1", "true", "yes"}

#: The userscript waits forever; give it a generous but finite window.
CLAIM_TIMEOUT = float(os.getenv("CLAIM_TIMEOUT", "300"))
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))

ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "/app/artifacts"))

#: Exact label first (what the userscript matches), then a tolerant form for
#: locales or amounts such as "Claim 25,000 Buzz".
CLAIM_TEXT = os.getenv("CLAIM_TEXT", "Claim 25 Buzz")
CLAIM_RE = re.compile(r"claim\s*[\d,]*\s*buzz", re.I)

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_CONFIG = 2


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
        for candidate in ("/usr/bin/chromedriver", "/usr/bin/msedgedriver"):
            if Path(candidate).exists():
                driver_path = candidate
                break

    args = [
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--window-size=1440,900",
        "--lang=en-US",
        f"--user-agent={USER_AGENT}",
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


# --------------------------------------------------------------------------- #
# The only job: find and press "Claim 25 Buzz"
# --------------------------------------------------------------------------- #

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
match.setAttribute('data-ndf-claim', '1');
return (match.textContent || '').trim();
"""


def find_claim_button(driver):
    """Locate the button the way the userscript does, straight from the DOM."""
    try:
        label = driver.execute_script(FIND_JS, CLAIM_TEXT, CLAIM_RE.pattern)
    except (JavascriptException, WebDriverException):
        return None
    if not label:
        return None
    try:
        return driver.find_element(By.CSS_SELECTOR, "[data-ndf-claim='1']")
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


def already_claimed(driver) -> bool:
    text = page_text(driver).lower()
    return any(
        phrase in text
        for phrase in ("already claimed", "come back tomorrow", "come back in", "claimed today")
    )


def is_logged_in(driver) -> bool:
    """Logged out pages show a 'Sign in' button and no account menu."""
    try:
        for element in driver.find_elements(By.XPATH, "//button[normalize-space(.)='Sign in']"):
            if visible(driver, element):
                return False
    except WebDriverException:
        pass
    try:
        return any(
            visible(driver, e)
            for e in driver.find_elements(By.CSS_SELECTOR, "[aria-label='Account menu']")
        )
    except WebDriverException:
        return False


def claim(driver) -> str:
    """Poll for the button, click it once, then confirm."""
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

            # Confirm: the bar disappears, or the page says so.
            confirm_deadline = time.time() + 30
            while time.time() < confirm_deadline:
                text = page_text(driver).lower()
                if any(word in text for word in ("claimed", "you got", "+25", "success")):
                    return "claimed"
                if already_claimed(driver):
                    return "already"
                if find_claim_button(driver) is None:
                    return "claimed"
                time.sleep(POLL_INTERVAL)

            log("Clicked, but no confirmation appeared")
            return "clicked"

        if already_claimed(driver):
            return "already"
        time.sleep(POLL_INTERVAL)

    return "none" if is_logged_in(driver) else "failed"


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
            "  Docker : docker run --rm -e CIVITAI_COOKIE='a=b; c=d' civitai-buzz\n"
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
    parser.add_argument("--timeout", type=float, help="seconds to wait for the button")
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
        log(f"Installed {install_cookies(driver, pairs)} cookie entries")

        driver.get(SITE_URL)
        time.sleep(3)

        title = (driver.title or "").lower()
        body = page_text(driver)[:400].lower()
        if "just a moment" in title or "security verification" in body:
            log("Cloudflare is still challenging this session (refresh cf_clearance)")
            save_artifacts(driver, "cloudflare")
            return EXIT_FAIL

        log(f"Waiting up to {CLAIM_TIMEOUT:.0f}s for '{CLAIM_TEXT}'")
        result = claim(driver)

        if result in {"claimed", "clicked"}:
            log("Done: +25 Buzz")
            return EXIT_OK
        if result == "already":
            log("Nothing to do: already claimed today")
            return EXIT_OK
        if result == "none":
            log(
                "The claim button never appeared (already claimed today, or this "
                "account is not eligible). Set STRICT=true to treat it as a failure."
            )
            if not STRICT:
                return EXIT_OK

        save_artifacts(driver, "claim-failed")
        return EXIT_FAIL

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
