"""Optional browser smoke check. Requires playwright + a Chromium installation."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8765")
parser.add_argument("--chromium")
parser.add_argument("--screenshots", type=Path)
args = parser.parse_args()
with sync_playwright() as p:
    options = {"headless": True}
    if args.chromium:
        options["executable_path"] = args.chromium
    browser = p.chromium.launch(**options)
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(args.url)
    page.wait_for_selector(".incident")
    count = page.locator(".incident").count()
    assert count == 9, f"Expected cascade fixture (9 incidents), got {count}"
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(args.screenshots / "dashboard.png"), full_page=True)
    page.locator(".incident").first.click()
    page.wait_for_selector("dialog[open]")
    page.keyboard.press("Escape")
    assert page.locator("dialog[open]").count() == 0
    page.locator(".incident").first.click()
    page.locator("#close-detail").click()
    assert page.locator("dialog[open]").count() == 0
    page.locator("#filter").select_option("resolved")
    assert page.locator(".empty").count() >= 1
    page.locator("#filter").select_option("open")
    page.locator("#refresh").click()
    page.wait_for_timeout(300)
    assert page.locator(".incident").count() == 9
    page.set_viewport_size({"width": 390, "height": 844})
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), "Mobile horizontal overflow"
    if args.screenshots:
        page.screenshot(path=str(args.screenshots / "dashboard-mobile.png"), full_page=True)
    assert not errors, errors
    print(json.dumps({"passed": True, "incidents": count, "javascript_errors": errors, "mobile_overflow": False}))
    browser.close()
