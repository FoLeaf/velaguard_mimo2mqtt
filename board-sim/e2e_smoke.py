"""Headless smoke test for the VelaGuard board simulator.

Requires: python-playwright and a local Chrome/Edge channel.

Usage:
    python board-sim/e2e_smoke.py            # mock + layout checks
    python board-sim/e2e_smoke.py --real     # also one real diagnosis (needs dev broker)

Exits non-zero on failure and prints a short JSON report on success.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = Path(__file__).resolve().parent.joinpath("index.html").as_uri()
VIEWPORTS = [(1366, 768), (1920, 1080)]


def check_mock(page) -> None:
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
        scroll_h = page.evaluate("document.documentElement.scrollHeight")
        inner_h = page.evaluate("window.innerHeight")
        assert scroll_h <= inner_h, f"{width}x{height} page scrolls"
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
            check_layouts(browser, errors)
            if args.real:
                report["real"] = check_real(page)
            report["mock"] = {"ok": True}
            if errors:
                report["console_errors"] = errors
                raise AssertionError("console errors: " + "; ".join(errors))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
