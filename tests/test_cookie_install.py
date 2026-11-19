"""Cookie-installation regression tests (no browser needed).

Civitai's session cookie moved to the ``__Host-`` prefix. Chrome enforces the
prefix rules, so a ``__Host-`` cookie set with a ``Domain`` is rejected with
"Sanitizing cookie failed" and the session silently stays logged out (401).
These tests pin the target selection that avoids that.
"""

import sys
from pathlib import Path
from unittest import TestCase, main

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import buzz  # noqa: E402


class FakeDriver:
    def __init__(self, refuse=()):
        self.calls = []
        self.refuse = set(refuse)

    def execute_cdp_cmd(self, command, params):
        self.calls.append(params)
        if params["name"] in self.refuse:
            return {"success": False}
        return {"success": True}


class InstallCookiesTest(TestCase):
    def test_host_cookie_has_no_domain_and_single_target(self):
        driver = FakeDriver()
        installed = buzz.install_cookies(
            driver, [("__Host-civ-token", "jwt"), ("civ-trpc-pool", "1")]
        )

        host = [c for c in driver.calls if c["name"] == "__Host-civ-token"]
        self.assertEqual(len(host), 1)
        self.assertNotIn("domain", host[0])
        self.assertEqual(host[0]["path"], "/")
        self.assertTrue(host[0]["secure"])

        normal = [c for c in driver.calls if c["name"] == "civ-trpc-pool"]
        self.assertEqual(len(normal), 2)
        self.assertEqual({c["domain"] for c in normal}, {".civitai.red", ".civitai.com"})

        self.assertEqual(installed, 3)

    def test_policy_refusal_is_not_counted_as_installed(self):
        driver = FakeDriver(refuse={"__Host-civ-token"})
        installed = buzz.install_cookies(driver, [("__Host-civ-token", "jwt")])
        self.assertEqual(installed, 0)

    def test_old_secure_prefix_still_works(self):
        driver = FakeDriver()
        buzz.install_cookies(driver, [("__Secure-civ-token", "jwt")])
        self.assertEqual(len(driver.calls), 2)
        self.assertTrue(all(c["secure"] for c in driver.calls))


if __name__ == "__main__":
    main()
