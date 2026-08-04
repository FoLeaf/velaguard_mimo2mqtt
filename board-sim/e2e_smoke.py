"""Headless smoke test for the unified VelaGuard board and debug console.

Requires: python-playwright and a local Chrome/Edge channel.

Usage:
    python board-sim/e2e_smoke.py            # mock + layout + unified drawer checks
    python board-sim/e2e_smoke.py --real     # also one real diagnosis (needs dev broker)

Exits non-zero on failure and prints a short JSON report on success.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
URL = (ROOT / "board-sim" / "index.html").as_uri()
COMPAT_URL = (ROOT / "debug-console" / "index.html").as_uri()
VIEWPORTS = [(1366, 768), (1920, 1080)]


def check_mock(page) -> None:
    page.click("#debug-drawer-toggle")
    page.click("[data-testid='mode-mock']")
    for scenario in ["warn", "crit", "offline", "ai_down", "ota", "normal"]:
        page.click(f"[data-testid='scenario-{scenario}']")
    page.click("[data-testid='home-action-logs']")
    assert page.locator("[data-testid='log-list'] .log-row").count() > 0
    page.click("#back-btn")
    page.click("[data-testid='home-action-diagnosis']")
    page.wait_for_selector(
        "[data-testid='diag-state'][data-diag-state='ok']", timeout=5000
    )
    assert page.locator("[data-testid='diag-summary']").inner_text().strip()
    page.click("#debug-drawer-close")


def check_unified_drawer(page) -> None:
    page.click("#debug-drawer-toggle")
    page.wait_for_selector("#debug-drawer")
    assert page.locator("#debug-drawer").is_visible()
    assert page.locator("#debug-drawer-collapse").is_visible()
    page.click("[data-testid='mode-mock']")
    page.click("#btn-clear-history")
    assert page.evaluate("window.__boardSim.getState().mode") == "mock"
    assert page.evaluate("window.__requestService.getState().mode") == "mock"

    page.select_option("#f-scenario", "fallback")
    page.click("#btn-send")
    page.wait_for_selector("#response-body:not([hidden])", timeout=5000)
    assert page.locator("#history-list .history-item").count() == 1
    assert page.locator("#timeline .timeline-item").count() >= 2
    page.wait_for_function("window.__requestService.getState().pendingCount === 0", timeout=5000)
    assert page.evaluate("window.__requestService.getState().pendingCount") == 0
    assert page.locator("#response-empty").get_attribute("hidden") is not None
    page.click("#traffic-toggle")
    page.wait_for_timeout(100)
    assert page.locator("#traffic-panel").is_visible()
    assert (page.locator("#response-panel").bounding_box() or {}).get("height", 0) >= 500
    assert (page.locator("#timeline-section").bounding_box() or {}).get("height", 0) >= 160
    assert (page.locator("#history-section").bounding_box() or {}).get("height", 0) >= 160

    # Invalid JSON must be rejected without creating another history entry.
    event_section = page.locator(".context-section[data-section='event']")
    event_section.locator("[data-mode='json']").click()
    event_section.locator(".json-editor").fill("{")
    page.wait_for_timeout(150)
    before = page.locator("#history-list .history-item").count()
    page.click("#btn-send")
    page.wait_for_timeout(150)
    assert page.locator("#status-message").inner_text().startswith("发送失败")
    assert page.locator("#history-list .history-item").count() == before

    page.click("#debug-drawer-collapse")
    assert not page.locator("#debug-drawer").is_visible()


def check_compat(browser, errors: list[str]) -> None:
    page = browser.new_page(viewport={"width": 1366, "height": 768})
    page.on(
        "console",
        lambda msg: errors.append(msg.text) if msg.type == "error" else None,
    )
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(COMPAT_URL, wait_until="load")
    page.wait_for_function("window.__boardSim !== undefined")
    assert "board-sim/index.html" in page.url
    page.close()


def check_layouts(browser, errors: list[str]) -> None:
    for width, height in VIEWPORTS:
        page = browser.new_page(viewport={"width": width, "height": height})
        page.on(
            "console",
            lambda msg: errors.append(msg.text) if msg.type == "error" else None,
        )
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(URL, wait_until="load")
        page.wait_for_function("window.__boardSim !== undefined")
        assert page.evaluate("document.documentElement.scrollHeight") <= page.evaluate("window.innerHeight"), f"{width}x{height} page scrolls closed"
        page.click("#debug-drawer-toggle")
        page.wait_for_timeout(150)
        assert page.evaluate("document.documentElement.scrollHeight") <= page.evaluate("window.innerHeight"), f"{width}x{height} page scrolls open"
        assert page.locator("#debug-drawer").is_visible()
        page.close()


def check_real(page) -> dict:
    page.click("[data-testid='mode-real']")
    if page.evaluate("window.__boardSim.getState().page") != "home":
        page.click("#back-btn")
    page.click("[data-testid='home-action-diagnosis']")
    page.wait_for_function(
        "() => { const s = window.__boardSim.getState(); return !!s.lastTerminal; }",
        timeout=75000,
    )
    state = page.evaluate("window.__boardSim.getState()")
    terminal = state["lastTerminal"] or {}
    if state["diagnosis"]["state"] != "ok":
        raise AssertionError(
            "real diagnosis failed: "
            + str(state["diagnosis"].get("error_code"))
            + " "
            + str(state["diagnosis"].get("error_msg"))
        )
    assert terminal["status"] == "success"
    return {
        "req_id": terminal["reqId"],
        "status": terminal["status"],
        "source": terminal["source"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="run one real diagnosis")
    args = parser.parse_args()

    errors: list[str] = []
    report: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.on(
                "console",
                lambda msg: errors.append(msg.text) if msg.type == "error" else None,
            )
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(URL, wait_until="load")
            page.wait_for_function("window.__boardSim !== undefined")
            check_mock(page)
            check_unified_drawer(page)
            check_layouts(browser, errors)
            check_compat(browser, errors)
            if args.real:
                report["real"] = check_real(page)
            report["mock"] = {"ok": True}
            report["unified_drawer"] = {"ok": True}
            if errors:
                report["console_errors"] = errors
                raise AssertionError("console errors: " + "; ".join(errors))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
