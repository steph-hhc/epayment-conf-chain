"""Drive the dashboard end-to-end and save screenshots for the report and slides.

Requires a running network (run_network.py), seeded data (seed_demo.py), and
auto-mining on. Uses the locally installed Microsoft Edge through Playwright.

    python scripts/capture_screenshots.py
"""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
BASE = "http://127.0.0.1:5001"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    wallets = [json.loads(p.read_text()) for p in sorted((ROOT / "wallets").glob("*.json"))]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5, color_scheme="light")
        page = ctx.new_page()
        page.goto(BASE)
        page.evaluate("w => { localStorage.setItem('confchain.wallets.v1', JSON.stringify(w)); localStorage.setItem('confchain.node', JSON.stringify(location.origin)); }", wallets)

        def shot(name, full=False):
            time.sleep(1.8)
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
            print("saved", name)

        def crop(name, selector):
            time.sleep(0.5)
            page.locator(selector).first.screenshot(path=str(OUT / f"{name}.png"))

        def go(hash_):
            page.goto(f"{BASE}/#{hash_}")
            page.wait_for_selector("#page-title")
            time.sleep(1.5)

        # 1 dashboard
        go("dashboard"); shot("01_dashboard"); crop("el_chain_strip", ".card:has(#d-chain)")

        # 2 wallet creation + registration
        go("wallet")
        page.fill("#w-create input[name=name]", "Ivy Yu")
        page.fill("#w-create input[name=email]", "ivy.yu@connect.edu")
        page.fill("#w-create input[name=pw]", "ivy-pass-2026")
        page.click("#w-create button")
        page.wait_for_selector("text=Wallet created")
        card = page.locator(".wallet", has_text="Ivy Yu")
        card.scroll_into_view_if_needed()
        shot("02_wallet_created")
        card.locator("[data-act=register]").click()
        page.wait_for_selector("text=Registration signed")
        shot("03_registration_broadcast")
        page.wait_for_function("() => [...document.querySelectorAll('.wallet')].some(w => w.textContent.includes('Ivy Yu') && w.textContent.includes('Registered ·'))", timeout=60000)
        page.locator(".wallet", has_text="Ivy Yu").scroll_into_view_if_needed()
        shot("04_registration_confirmed")

        # 3 check-in (valid)
        go("checkin")
        ivy = next(o for o in page.eval_on_selector_all("#c-wallet option", "os => os.map(o => [o.value, o.textContent])") if "Ivy" in o[1])[0]
        page.select_option("#c-wallet", ivy)
        page.click("[data-sid=S5]")
        page.click("#c-go")
        page.wait_for_selector("text=Certificate broadcast")
        shot("05_checkin_pending")
        page.wait_for_selector("text=Confirmed in block", timeout=60000)
        shot("06_checkin_confirmed")

        # 4 forged certificate
        go("checkin")
        felix = next(o for o in page.eval_on_selector_all("#c-wallet option", "os => os.map(o => [o.value, o.textContent])") if "Felix" in o[1])[0]
        page.select_option("#c-wallet", felix)
        page.fill("#c-pw", "demo1234")
        page.click("[data-sid=S2]")
        page.check("#c-forge")
        page.select_option("#c-forge-to", "S5")
        page.click("#c-go")
        page.wait_for_selector("text=Rejected by the miner", timeout=60000)
        shot("07_forged_rejected"); crop("el_forged", ".card:has(#c-steps)")

        # 5 mining + difficulty
        go("mining"); page.wait_for_selector("text=Mining block", timeout=30000); shot("08_mining")
        go("difficulty"); shot("09_difficulty", full=True); crop("el_difficulty_chart", ".card:has(#df-chart)"); crop("el_retargets", ".card:has(#df-table)")

        # 6 queries
        go("queries")
        page.click("[data-tab=q1]"); page.fill("#q1-in", "Alice"); page.click("#q-run"); page.wait_for_selector("text=attended"); shot("10_q1_sessions_of_attendee"); crop("el_q1", "#q-card")
        page.locator("button", has_text="Verify signature").first.click(); page.wait_for_selector("dialog[open]"); shot("11_verify_signature")
        page.keyboard.press("Escape")
        page.click("[data-tab=q2]"); page.select_option("#q2-in", "S1"); page.click("#q-run"); page.wait_for_selector("text=participant(s) attended"); shot("12_q2_attendees_of_session"); crop("el_q2", "#q-card")
        page.click("[data-tab=q3]"); page.select_option("#q3-in", "S1"); page.click("#q-run"); page.wait_for_selector("text=did not attend"); shot("13_q3_absentees"); crop("el_q3", "#q-card")
        page.click("[data-tab=q4]"); page.fill("#q4-in", "ivy.yu@connect.edu"); page.click("#q-run"); page.wait_for_selector(".callout"); shot("14_q4_status_confirmed"); crop("el_q4", "#q-card")
        page.fill("#q4-in", "nobody@connect.edu"); page.click("#q-run"); time.sleep(1); shot("15_q4_status_not_registered")

        # 7 explorer + block detail, and a second node's view
        go("explorer"); shot("16_explorer")
        page.locator("tr[data-block]").nth(3).click(); page.wait_for_selector("dialog[open]"); shot("17_block_detail")
        page.keyboard.press("Escape")
        page.select_option("#node-select", "http://127.0.0.1:5003")
        go("dashboard"); shot("18_node_c_dashboard")
        page.select_option("#node-select", BASE)
        browser.close()


if __name__ == "__main__":
    main()
