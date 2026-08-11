"""Headed Playwright E2E test for the Coding Agent."""
import sys
import io
import asyncio

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


async def sc(page, sel, t=3000):
    try:
        el = await page.wait_for_selector(sel, timeout=t)
        if el:
            await el.click()
            return True
    except Exception:
        pass
    return False


async def test():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False, slow_mo=150,
            args=['--window-size=1200,720', '--window-position=80,40']
        )
        page = await browser.new_page(viewport={'width': 1200, 'height': 720})
        await page.goto('http://localhost:8000/', wait_until='domcontentloaded', timeout=15000)
        await asyncio.sleep(4)
        await sc(page, 'text=Maybe later')
        await sc(page, 'text=Dismiss tour')
        await asyncio.sleep(0.5)

        print("Opening Code tab...")
        await page.keyboard.press('Control+k')
        await asyncio.sleep(1)
        await page.keyboard.type('code')
        await asyncio.sleep(1)
        await sc(page, '[data-name="code_agent"]')
        await asyncio.sleep(2)

        print("Focusing chat and sending request...")
        await page.evaluate('() => document.querySelector("#chat-input")?.focus()')
        await asyncio.sleep(0.5)
        await page.keyboard.type(
            "when I close a tab at the top, fix the auto scrolling of other tabs"
        )
        await asyncio.sleep(1)
        await page.keyboard.press('Enter')
        print("Request sent! Watching for 3 minutes...")

        for i in range(36):
            await asyncio.sleep(5)
            elapsed = (i + 1) * 5
            has_card = await page.evaluate(
                '() => !!document.querySelector(".ca-change-card")'
            )
            session_vis = await page.evaluate(
                '() => { const e=document.getElementById("ca-active-session"); '
                'return e ? window.getComputedStyle(e).display !== "none" : false; }'
            )
            if has_card:
                txt = await page.evaluate(
                    '() => document.querySelector(".ca-change-card")?.innerText||""'
                )
                print(f"\n[{elapsed}s] CHANGE CARD FOUND!")
                print(txt.encode('ascii', 'replace').decode()[:400])
                await page.screenshot(path='/tmp/real_card.png')
                ok = await sc(page, '.ca-btn-approve')
                await asyncio.sleep(3)
                applied = await page.evaluate(
                    '() => !!document.querySelector(".ca-applied-row")'
                )
                print(f"Approve clicked={ok} Applied row={applied}")
                await page.screenshot(path='/tmp/real_approved.png')
                break
            prog = await page.evaluate(
                '() => document.getElementById("ca-progress-log")?.innerText||""'
            )
            prog_short = prog.strip()[:70].encode('ascii', 'replace').decode()
            print(f"[{elapsed}s] session_visible={session_vis} | {prog_short}")

        print("\nBrowser stays open 20s for you to interact...")
        await asyncio.sleep(20)
        await browser.close()


asyncio.run(test())
