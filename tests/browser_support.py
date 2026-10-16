"""Helpers for the browser tests (tests/browser/)."""

import time


def wait_js(page, expression: str, timeout: float = 10.0):
    """Poll a JavaScript expression until it is truthy and return its value.

    Playwright's wait_for_function polls with eval, which the app's
    content-security policy (rightly) blocks; page.evaluate is not subject to it.
    """
    deadline = time.monotonic() + timeout
    while True:
        value = page.evaluate(expression)
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for: {expression}")
        page.wait_for_timeout(50)
