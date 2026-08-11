"""
Coding Agent E2E test — non-headless so you can watch.
Tests:
  1. Code tab opens cleanly (no 'Select an item' placeholder)
  2. Project switcher shows active project
  3. Chat request triggers coding session without asking for repo path
  4. Change card appears with Approve/Decline buttons
  5. Approve commits the change
"""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


async def run():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--window-size=1400,800", "--window-position=20,20"],
        )
        page = await browser.new_page(viewport={"width": 1400, "height": 800})

        # ── 1. Load the app ────────────────────────────────────────────────────
        print("Loading AI Gator...")
        await page.goto("http://localhost:8000/", wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(4)

        # Dismiss any modals
        for sel in ["text=Maybe later", "text=Dismiss tour"]:
            try:
                el = await page.wait_for_selector(sel, timeout=2000)
                if el:
                    await el.click()
                    await asyncio.sleep(0.3)
            except Exception:
                pass

        # ── 2. Open Code tab ───────────────────────────────────────────────────
        print("\nStep 1: Opening Code tab via Ctrl+K...")
        await page.keyboard.press("Control+k")
        await asyncio.sleep(1)
        await page.keyboard.type("code")
        await asyncio.sleep(1)
        code_item = await page.query_selector('[data-name="code_agent"]')
        if code_item:
            await code_item.click()
            await asyncio.sleep(2)
            print("  Code tab opened")
        else:
            print("  ERROR: Code tab not found in picker")
            await browser.close()
            return

        # ── 3. Check no placeholder ────────────────────────────────────────────
        print("\nStep 2: Checking Code tab content...")
        placeholder = await page.evaluate(
            '() => document.getElementById("tp-detail-col")?.innerText || ""'
        )
        if "Select an item" in placeholder:
            print("  FAIL: Still showing 'Select an item' placeholder")
        else:
            print("  PASS: No placeholder")

        switcher = await page.evaluate(
            '() => document.querySelector(".ca-project-switcher")?.textContent || "none"'
        )
        print(f"  Project switcher: {switcher.encode('ascii','replace').decode()}")
        await page.screenshot(path="/tmp/step2_code_tab.png")

        # ── 4. Focus chat and type request ─────────────────────────────────────
        print("\nStep 3: Typing coding request...")
        chat_input = page.locator("#chat-input")
        await chat_input.click()
        await asyncio.sleep(0.5)
        await chat_input.type(
            "when I close a tab at the top, fix the auto scrolling of other tabs",
            delay=30
        )
        await asyncio.sleep(1)
        await page.screenshot(path="/tmp/step3_typed.png")

        chip = await page.evaluate(
            "() => !!document.querySelector('.chat-chip[data-skill-id=\"code_agent\"]')"
        )
        print(f"  /code chip active: {chip}")

        # ── 5. Submit via chat-form submit event (same path as Enter key) ──────
        # The app's keydown handler does:
        #   document.getElementById('chat-form').dispatchEvent(new Event('submit',...))
        # We do the same — reliable regardless of button position.
        print("\nStep 4: Submitting via chat-form submit event...")
        submitted = await page.evaluate("""() => {
            const form = document.getElementById('chat-form');
            if (!form) return 'no-form';
            form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
            return 'submitted';
        }""")
        print(f"  Result: {submitted}")
        await asyncio.sleep(2)
        await page.screenshot(path="/tmp/step4_sent.png")

        # ── 6. Watch for change card ───────────────────────────────────────────
        print("\nStep 5: Waiting for change card (up to 3 minutes)...")
        card_found = False
        for i in range(36):
            await asyncio.sleep(5)
            elapsed = (i + 1) * 5

            has_card = await page.evaluate(
                "() => !!document.querySelector('.ca-change-card')"
            )
            session_vis = await page.evaluate(
                "() => { const e=document.getElementById('ca-active-session');"
                " return e ? window.getComputedStyle(e).display !== 'none' : false; }"
            )
            prog = await page.evaluate(
                "() => document.getElementById('ca-progress-log')?.innerText || ''"
            )
            prog_clean = prog.strip()[:80].encode("ascii", "replace").decode()

            if has_card:
                card_found = True
                txt = await page.evaluate(
                    "() => document.querySelector('.ca-change-card')?.innerText || ''"
                )
                print(f"\n[{elapsed}s] *** CHANGE CARD APPEARED ***")
                print(txt.encode("ascii", "replace").decode()[:500])
                await page.screenshot(path="/tmp/step5_card.png")

                # ── 7. Click Approve ───────────────────────────────────────────
                print("\nStep 6: Clicking Approve...")
                approve_btn = page.locator(".ca-btn-approve").first
                await approve_btn.scroll_into_view_if_needed()
                await approve_btn.click()
                await asyncio.sleep(3)

                applied = await page.evaluate(
                    "() => !!document.querySelector('.ca-applied-row')"
                )
                print(f"  Applied row visible: {applied}")
                await page.screenshot(path="/tmp/step6_approved.png")
                break

            print(f"[{elapsed}s] session={session_vis} | {prog_clean}")

            if elapsed % 30 == 0:
                await page.screenshot(path=f"/tmp/progress_{elapsed}s.png")

        if not card_found:
            await page.screenshot(path="/tmp/no_card_timeout.png")
            print("\nNo change card after 3 minutes")
            tab_content = await page.evaluate(
                "() => document.getElementById('tp-detail-col')?.innerText?.slice(0,200) || 'empty'"
            )
            print("Code tab:", tab_content.encode("ascii", "replace").decode())

        print("\nBrowser stays open 30s for you to interact...")
        await asyncio.sleep(30)
        await browser.close()
        print("Done.")


asyncio.run(run())
