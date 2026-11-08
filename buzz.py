#!/usr/bin/env python3
"""
Civitai-Buzz
============

每天領取 Civitai 的 25 Buzz。

流程：
  1. 用你提供的 Cookie 登入（不用帳號密碼）
  2. 開啟 https://civitai.red/
  3. 點導覽列的「Create」
  4. 在彈出選單中點「Claim 25 Buzz」
  5. 確認結果後結束

為什麼是 Cookie：這個站台在 Cloudflare 後面，無頭瀏覽器過不了「Just a moment...」。
把瀏覽器裡真正的 cookie（含 cf_clearance）餵進來，才是最穩定的做法。
cf_clearance 綁 IP + User-Agent，所以請在**同一台機器／同一個網路**上執行，並讓
USER_AGENT 與當初領取 cookie 的瀏覽器一致。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
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
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

SITE_URL = os.getenv("CIVITAI_URL", "https://civitai.red/generate").rstrip("/")
if SITE_URL.count("/") == 2:  # bare origin -> default page
    SITE_URL = SITE_URL + "/generate"
COOKIE_RAW = os.getenv("CIVITAI_COOKIE", "")

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
)
USER_AGENT = os.getenv("USER_AGENT", DEFAULT_UA)

BROWSER = os.getenv("BROWSER", "chrome").strip().lower()
HEADLESS = os.getenv("HEADLESS", "true").strip().lower() not in {"0", "false", "no"}
DEBUG = os.getenv("DEBUG", "false").strip().lower() in {"1", "true", "yes"}
#: Fail (exit 1) when the claim entry is missing instead of treating it as done.
STRICT = os.getenv("STRICT", "false").strip().lower() in {"1", "true", "yes"}

LOGIN_TIMEOUT = float(os.getenv("LOGIN_TIMEOUT", "90"))
ACTION_TIMEOUT = float(os.getenv("ACTION_TIMEOUT", "30"))
ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "/app/artifacts"))

#: Navbar "Create" button, exactly as it appears in the page source.
SEL_CREATE = "[data-activity='create:navbar']"
#: Create is a split button: the caret next to it opens the menu, the label
#: itself navigates to /create.
SEL_CREATE_CARET = "button[data-activity='create:navbar'] + button"
#: The daily buzz entry inside the Create popover.
CLAIM_RE = re.compile(r"claim\s*[\d,]*\s*buzz", re.I)
CLAIM_TIMEOUT = float(os.getenv("CLAIM_TIMEOUT", "150"))

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
        # Windows consoles default to cp950/cp1252; emoji in button labels
        # must not take the whole run down.
        encoding = sys.stdout.encoding or "utf-8"
        print(text.encode(encoding, "replace").decode(encoding, "replace"), flush=True)


def norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def visible(element) -> bool:
    try:
        return bool(element.is_displayed())
    except (StaleElementReferenceException, WebDriverException):
        return False


def first_visible(driver, css: str, timeout: float = 0.0):
    deadline = time.time() + timeout
    while True:
        try:
            for element in driver.find_elements(By.CSS_SELECTOR, css):
                if visible(element):
                    return element
        except WebDriverException:
            pass
        if time.time() >= deadline:
            return None
        time.sleep(0.3)


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


def page_text(driver) -> str:
    try:
        return norm(driver.find_element(By.TAG_NAME, "body").text)
    except WebDriverException:
        return ""


def save_artifacts(driver, tag: str) -> None:
    try:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        driver.save_screenshot(str(ARTIFACTS_DIR / f"{stamp}-{tag}.png"))
        (ARTIFACTS_DIR / f"{stamp}-{tag}.html").write_text(driver.page_source, encoding="utf-8")
        log(f"Debug artifacts written to {ARTIFACTS_DIR}")
    except Exception as exc:
        log(f"Could not write artifacts: {exc}")


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
        name = name.strip()
        value = value.strip().strip('"')
        if name:
            pairs.append((name, value))
    return pairs


def install_cookies(driver, pairs: list[tuple[str, str]]) -> int:
    """Set cookies for every host we might touch (civitai.red / civitai.com)."""
    domains = [".civitai.red", ".civitai.com"]
    installed = 0
    for name, value in pairs:
        for domain in domains:
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


def build_driver():
    driver_path = os.getenv("WEBDRIVER_PATH")
    if not driver_path:
        for candidate in ("/usr/bin/chromedriver", "/usr/bin/msedgedriver"):
            if Path(candidate).exists():
                driver_path = candidate
                break

    common = [
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
    ]
    if HEADLESS:
        common.insert(0, "--headless=new")

    if BROWSER in {"edge", "msedge"}:
        from selenium.webdriver.edge.options import Options as EdgeOptions
        from selenium.webdriver.edge.service import Service as EdgeService

        options = EdgeOptions()
        for argument in common:
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
        for argument in common:
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


def is_cloudflare_challenge(driver) -> bool:
    title = (driver.title or "").lower()
    body = page_text(driver)[:500].lower()
    return (
        "just a moment" in title
        or "security verification" in body
        or "checking your browser" in body
        or "enable javascript and cookies" in body
    )


# --------------------------------------------------------------------------- #
# Claiming
# --------------------------------------------------------------------------- #


def open_create_menu(driver) -> bool:
    """The label navigates to /create; the caret beside it opens the menu."""
    caret = first_visible(driver, SEL_CREATE_CARET, timeout=15)
    target = caret or first_visible(driver, SEL_CREATE, timeout=10)
    if target is None:
        log("Create button not found (navbar may not have rendered)")
        return False
    if not click(driver, target):
        log("Create button could not be clicked")
        return False
    log("Opened Create menu" if caret is not None else "Clicked Create")
    time.sleep(1.5)
    return True


def menu_items(driver) -> list[str]:
    """Text of everything that looks like a menu entry (for diagnostics)."""
    labels = []
    try:
        elements = driver.find_elements(
            By.CSS_SELECTOR, "[role='menuitem'], [role='menu'] button, .mantine-Menu-item"
        )
    except WebDriverException:
        return labels
    for element in elements:
        if visible(element):
            text = norm(element.text)
            if text:
                labels.append(text[:60])
    return labels


FIND_CLAIM_JS = """
const re = /claim\\s*[\\d,]*\\s*buzz/i;
const nodes = document.querySelectorAll('button, [role="button"], a, [role="menuitem"]');
for (const n of nodes) {
    const text = (n.innerText || n.textContent || '').replace(/\\s+/g, ' ').trim();
    const aria = (n.getAttribute('aria-label') || '');
    if (re.test(text) || re.test(aria)) {
        n.setAttribute('data-ndf-claim', '1');
        return text || aria;
    }
}
return '';
"""

#: The claim bar sits at the bottom of the left sidebar and renders late; walk
#: every scrollable container so lazily mounted sections exist before we look.
REVEAL_JS = """
const scrolled = [];
document.querySelectorAll('*').forEach(function (el) {
    if (el.scrollHeight > el.clientHeight + 40 && el.clientHeight > 100) {
        el.scrollTop = el.scrollHeight;
        scrolled.push(el.tagName);
    }
});
return scrolled.length;
"""


def find_claim_button(driver):
    """Look for 'Claim N Buzz' through the DOM, not just what is in the viewport."""
    try:
        text = driver.execute_script(FIND_CLAIM_JS)
    except (JavascriptException, WebDriverException):
        return None
    if not text:
        return None
    try:
        return driver.find_element(By.CSS_SELECTOR, "[data-ndf-claim='1']")
    except (NoSuchElementException, WebDriverException):
        return None


def reveal_lazy_sections(driver) -> None:
    try:
        driver.execute_script(REVEAL_JS)
    except (JavascriptException, WebDriverException):
        pass


def buzz_widget(driver) -> bool:
    """The logged-in navbar keeps the buzz balance behind a popover trigger."""
    try:
        elements = driver.find_elements(
            By.CSS_SELECTOR, "[aria-haspopup='dialog'], [aria-haspopup='menu']"
        )
    except WebDriverException:
        return False

    for element in elements:
        if not visible(element):
            continue
        text = norm(element.text).lower()
        if not text or len(text) > 40:
            continue
        if any(word in text for word in ("buy", "get buzz", "purchase", "top up")):
            continue
        if "buzz" in text or re.fullmatch(r"[\d,.\s]+", text):
            if click(driver, element):
                log(f"Opened buzz widget ({text!r})")
                time.sleep(1.5)
                return True
    return False


def open_account_menu(driver) -> bool:
    """Daily claims are often tucked into the avatar menu rather than Create."""
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, "button, [role='button']")
    except WebDriverException:
        return False

    for element in elements:
        if not visible(element):
            continue
        label = (norm(element.text) + " " + norm(element.get_attribute("aria-label"))).lower()
        if any(word in label for word in ("sign in", "log in", "login", "support", "buy", "purchase")):
            continue
        if any(word in label for word in ("account", "profile", "avatar", "user menu", "my account")):
            if click(driver, element):
                log(f"Opened account menu ({label.strip()!r})")
                time.sleep(1.5)
                return True
    return False


def dump_ui(driver) -> None:
    """Log what is actually on screen -- the fastest way to fix a selector."""
    try:
        log(f"Page: {driver.title!r} {driver.current_url}")
    except WebDriverException:
        pass

    texts = []
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, "button, [role='button']")
    except WebDriverException:
        return
    for element in elements:
        try:
            if not visible(element):
                continue
            text = norm(element.text)
            if text:
                texts.append(text[:40])
        except (StaleElementReferenceException, WebDriverException):
            continue

    if texts:
        log(f"Visible buttons ({len(texts)}): {' | '.join(texts[:30])}")
    else:
        log("No visible buttons at all -- the page probably did not render")


def dismiss_onboarding(driver) -> None:
    """The /generate page can open a first-visit tour that swallows clicks.

    Mantine does not always put role="dialog" on the modal, so this also looks
    for the tour's buttons page-wide.
    """
    dismiss_labels = {"skip", "close", "close ad", "dismiss", "got it", "no thanks", "maybe later"}

    for _ in range(2):
        try:
            candidates = driver.find_elements(By.CSS_SELECTOR, "button, [role='button']")
        except WebDriverException:
            return

        clicked = False
        # Prefer a button inside a modal, then fall back to anywhere on the page.
        modals = []
        try:
            modals = [
                m for m in driver.find_elements(
                    By.CSS_SELECTOR, "[role='dialog'], .mantine-Modal-content, .mantine-Modal-root"
                ) if visible(m)
            ]
        except WebDriverException:
            pass

        for scope in modals + [None]:
            pool = candidates if scope is None else scope.find_elements(By.CSS_SELECTOR, "button, [role='button']")
            for element in pool:
                if not visible(element):
                    continue
                label = norm(element.text).lower()
                aria = norm(element.get_attribute("aria-label")).lower()
                if label in dismiss_labels or (aria == "close" and scope is not None):
                    if click(driver, element):
                        log(f"Dismissed dialog ({label or aria})")
                        clicked = True
                        break
            if clicked:
                break

        if not clicked:
            return
        time.sleep(1.0)


def already_claimed(driver) -> bool:
    text = page_text(driver).lower()
    return any(
        phrase in text
        for phrase in (
            "already claimed",
            "come back tomorrow",
            "come back in",
            "next claim",
            "claimed today",
        )
    )


def wait_for_claim_button(driver, timeout: float):
    """Return (element, status) where status is None or 'already'."""
    deadline = time.time() + timeout
    last_dismiss = 0.0
    while time.time() < deadline:
        # The first-visit tour can pop up a second or two after load and sit on
        # top of the button, so keep swatting it while we wait.
        if time.time() - last_dismiss > 3:
            dismiss_onboarding(driver)
            reveal_lazy_sections(driver)
            last_dismiss = time.time()

        item = find_claim_button(driver)
        if item is not None:
            return item, None
        if already_claimed(driver):
            return None, "already"
        time.sleep(0.5)
    return None, None


def wait_app_ready(driver, timeout: float) -> bool:
    """The shop renders the toolbar late; wait for it before hunting buttons."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if (
            first_visible(driver, SEL_CREATE, timeout=0) is not None
            or first_visible(driver, "[aria-label*='account' i]", timeout=0) is not None
            or find_claim_button(driver) is not None
        ):
            return True
        dismiss_onboarding(driver)
        time.sleep(1.0)
    return False


def close_popover(driver) -> None:
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    except WebDriverException:
        pass
    time.sleep(0.5)


def is_logged_in(driver) -> bool:
    """Logged out pages show a 'Sign in' button and no account menu."""
    try:
        for element in driver.find_elements(By.XPATH, "//button[normalize-space(.)='Sign in']"):
            if visible(element):
                return False
    except WebDriverException:
        pass
    return (
        first_visible(driver, "[aria-label='Account menu']", timeout=0) is not None
        or first_visible(driver, "[aria-label*='account' i]", timeout=0) is not None
    )


def claim(driver) -> str:
    """Return 'claimed', 'already' or 'failed'.

    The claim control appears late and has moved around between releases, so
    this waits for the toolbar, then tries: page -> buzz popover -> account
    menu -> Create menu, logging what each popover contained.
    """
    dismiss_onboarding(driver)
    if not wait_app_ready(driver, LOGIN_TIMEOUT):
        log("The toolbar never rendered")
        dump_ui(driver)
        return "failed"

    item, status = wait_for_claim_button(driver, CLAIM_TIMEOUT)
    if status == "already":
        log("Buzz already claimed today")
        return "already"

    if item is None:
        for name, opener in (
            ("buzz popover", buzz_widget),
            ("account menu", open_account_menu),
            ("Create menu", open_create_menu),
        ):
            if not opener(driver):
                continue
            log(f"Looking for the claim entry in the {name}")
            item, status = wait_for_claim_button(driver, CLAIM_TIMEOUT / 3)
            if status == "already":
                log("Buzz already claimed today")
                return "already"
            if item is not None:
                break
            labels = menu_items(driver)
            if labels:
                log(f"{name} contains: {' | '.join(labels[:15])}")
            close_popover(driver)

    if item is None:
        log("'Claim 25 Buzz' not found on the page")
        dump_ui(driver)
        # Everything rendered and we are logged in: the daily claim is simply
        # not on offer (already claimed today, or not eligible).
        return "none" if is_logged_in(driver) else "failed"

    log("Clicking 'Claim 25 Buzz'")
    if not click(driver, item):
        log("Claim button could not be clicked")
        return "failed"

    deadline = time.time() + ACTION_TIMEOUT
    while time.time() < deadline:
        text = page_text(driver).lower()
        if any(word in text for word in ("claimed", "you got", "+25", "success")):
            log("Buzz claimed")
            return "claimed"
        if already_claimed(driver):
            return "already"
        # The control disappearing is also a good sign.
        if find_claim_button(driver) is None and time.time() > deadline - ACTION_TIMEOUT + 6:
            log("Claim entry disappeared from the page")
            return "claimed"
        time.sleep(0.5)

    log("No confirmation after clicking the claim entry")
    return "failed"


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
    global DEBUG

    parser = argparse.ArgumentParser(description="Claim the daily 25 Buzz on Civitai")
    parser.add_argument("--cookie", help="full cookie header value")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--visible", action="store_true", help="show the browser window")
    args = parser.parse_args(argv or sys.argv[1:])

    DEBUG = DEBUG or args.debug
    if args.visible:
        globals()["HEADLESS"] = False

    try:
        raw_cookie = get_cookie(args)
    except SystemExit as exc:
        log(str(exc))
        return EXIT_CONFIG

    pairs = parse_cookie_header(raw_cookie)
    if not pairs:
        log("No usable cookies parsed")
        return EXIT_CONFIG
    log(f"Loaded {len(pairs)} cookie(s): {', '.join(name for name, _ in pairs)[:120]}")

    driver = None
    try:
        driver = build_driver()
        driver.set_page_load_timeout(90)

        # Cookies must exist before the first navigation, otherwise Cloudflare
        # has already handed us a challenge page.
        installed = install_cookies(driver, pairs)
        log(f"Installed {installed} cookie entries")

        driver.get(SITE_URL)
        time.sleep(3)

        if is_cloudflare_challenge(driver):
            log(
                "Cloudflare is still challenging this session. Refresh cf_clearance "
                "(and keep USER_AGENT identical to the browser that produced it)."
            )
            save_artifacts(driver, "cloudflare")
            return EXIT_FAIL

        result = claim(driver)

        if result == "claimed":
            log("Done: +25 Buzz")
            return EXIT_OK
        if result == "already":
            log("Nothing to do: already claimed today")
            return EXIT_OK
        if result == "none":
            log(
                "No claim entry offered (already claimed today, or this account "
                "is not eligible). Set STRICT=true to treat this as a failure."
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
            try:
                driver.quit()
            except WebDriverException:
                pass


if __name__ == "__main__":
    sys.exit(main())
