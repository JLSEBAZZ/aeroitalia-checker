#!/usr/bin/env python3
"""
Aeroitalia flight availability checker
Route: Milano Linate (LIN) → Cagliari (CAG)
Dates: 28/05/2026 and 29/05/2026

Run modes:
  python3 check_flights.py          → single check (used by GitHub Actions)
  python3 check_flights.py --loop   → loop every 15 min (local use)
"""

import re
import os
import sys
import time
import requests
from datetime import datetime
from dataclasses import dataclass, field
from playwright.sync_api import sync_playwright

# ─── Configuration ────────────────────────────────────────────────────────────
ORIGIN = "Linate"
DESTINATION = "Cagliari"
FLIGHT_DAYS = ["28", "29"]
FLIGHT_YEAR = "2026"

# Read from env vars (set as GitHub Secrets) or hardcoded fallback
TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "REDACTED"
)
TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID",
    "320925304"
)


# ─── Data model ───────────────────────────────────────────────────────────────
@dataclass
class Flight:
    date: str
    departure: str
    arrival: str
    flight_number: str
    duration: str
    fare_class: str
    price: str
    sold_out: bool = False


# ─── Scraper ──────────────────────────────────────────────────────────────────
def scrape_day(day: str) -> list[Flight]:
    flights: list[Flight] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="it-IT",
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(15000)

        page.goto("https://book.aeroitalia.com/", wait_until="networkidle", timeout=30000)
        time.sleep(2)

        page.locator("input[placeholder='Selezionare la partenza']").click()
        time.sleep(0.3)
        page.keyboard.type(ORIGIN, delay=80)
        time.sleep(2)
        page.keyboard.press("ArrowDown")
        time.sleep(0.2)
        page.keyboard.press("Enter")
        time.sleep(1)

        page.locator("input[placeholder='Selezionare la destinazione']").click()
        time.sleep(0.3)
        page.keyboard.type(DESTINATION, delay=80)
        time.sleep(2)
        page.keyboard.press("ArrowDown")
        time.sleep(0.2)
        page.keyboard.press("Enter")
        time.sleep(1)

        page.locator("input[value='Selezionare le date']").first.click(force=True)
        time.sleep(3)

        page.locator("text=Volo di sola andata").first.click(force=True)
        time.sleep(0.5)

        clicked = page.evaluate("""(day) => {
            for (const el of document.querySelectorAll('span, div')) {
                const text = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                if (rect.x <= 0 || rect.x >= 750) continue;
                if (rect.width < 40 || rect.height < 30) continue;
                if (!text.startsWith(day)) continue;
                if (!text.includes('€') && !text.toLowerCase().includes('sold')) continue;
                el.click();
                return {ok: true, text: text.substring(0, 30)};
            }
            return {ok: false};
        }""", day)

        if not clicked.get("ok"):
            print(f"    ⚠ Day {day}: cell not found in calendar")
            browser.close()
            return flights

        sold_out_day = "sold" in (clicked.get("text", "")).lower()
        time.sleep(1)

        try:
            page.locator("button:has-text('Fine')").first.click(force=True)
        except Exception:
            pass
        time.sleep(1)

        page.locator("button:has-text('Ricerca')").first.click(force=True)
        time.sleep(5)
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        time.sleep(8)

        # Scroll to load all flights
        prev_count = 0
        for _ in range(20):
            page.keyboard.press("End")
            time.sleep(0.5)
            page.evaluate("""() => {
                window.scrollTo(0, document.body.scrollHeight);
                document.querySelectorAll('ion-content').forEach(el => {
                    const inner = el.shadowRoot?.querySelector('.inner-scroll');
                    if (inner) inner.scrollTop = inner.scrollHeight;
                });
                document.querySelectorAll('[class*="scroll"], main, section').forEach(el => {
                    el.scrollTop = el.scrollHeight;
                });
            }""")
            time.sleep(0.8)
            cur_count = page.evaluate(f"""() => {{
                let count = 0;
                document.querySelectorAll('span, div').forEach(el => {{
                    const t = (el.textContent || '').trim();
                    if (t.includes('{day} mag 2026') && t.includes('Volo diretto')) count++;
                }});
                return count;
            }}""")
            if cur_count == prev_count and cur_count > 0:
                break
            prev_count = cur_count

        page.screenshot(path=f"last_check_{day}mag.png", full_page=True)

        body = page.locator("body").text_content() or ""

        if sold_out_day:
            flights.append(Flight(
                date=day, departure="--", arrival="--",
                flight_number="--", duration="--",
                fare_class="--", price="--", sold_out=True,
            ))
            browser.close()
            return flights

        pattern = (
            rf'(\d{{2}}:\d{{2}}){day} mag 2026Milano Linate'
            r'(1 ora \d+min)Volo diretto(XZ\d+)'
            rf'(\d{{2}}:\d{{2}}){day} mag 2026Cagliari'
            r'([A-Za-z]+)(\d+,\d{2})\s*€'
        )
        for m in re.finditer(pattern, body):
            flights.append(Flight(
                date=day,
                departure=m.group(1),
                arrival=m.group(4),
                flight_number=m.group(3),
                duration=m.group(2),
                fare_class=m.group(5),
                price=f"{m.group(6)}€",
            ))

        browser.close()

    return flights


# ─── Notifications ────────────────────────────────────────────────────────────
def send_telegram(message: str):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        }, timeout=10)
        if resp.ok:
            print("    ✈ Telegram sent")
        else:
            print(f"    ✈ Telegram error: {resp.text[:100]}")
    except Exception as e:
        print(f"    ✈ Telegram error: {e}")


# ─── Main check ──────────────────────────────────────────────────────────────
def run_check():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"  Flight check at {now}")
    print(f"  LIN → CAG — {' e '.join(f'{d}/05/{FLIGHT_YEAR}' for d in FLIGHT_DAYS)}")
    print(f"{'='*60}")

    all_results: dict[str, list[Flight]] = {}
    for day in FLIGHT_DAYS:
        print(f"\n--- {day}/05/{FLIGHT_YEAR} ---")
        try:
            all_results[day] = scrape_day(day)
        except Exception as e:
            print(f"  ❌ Error: {e}")
            all_results[day] = []

    msg_lines = [f"✈ *Aeroitalia LIN→CAG* — {now}"]

    for day, flights in all_results.items():
        label = f"\n📅 *{day}/05/{FLIGHT_YEAR}*"
        if not flights:
            print(f"\n  {day}/05: ⚠ nessun dato")
            msg_lines.append(f"{label}\n⚠ nessun dato")
            continue
        if flights[0].sold_out:
            print(f"\n  {day}/05: ❌ SOLD OUT")
            msg_lines.append(f"{label}\n❌ Sold Out")
            continue

        cheapest = min(flights, key=lambda f: float(f.price.replace("€","").replace(",",".")))
        print(f"\n  {day}/05 — {len(flights)} voli:")
        print(f"  {'Orario':<16} {'Volo':<10} {'Prezzo':>8}")
        print(f"  {'-'*16} {'-'*10} {'-'*8}")
        for f in flights:
            print(f"  {f.departure}→{f.arrival:<10} {f.flight_number:<10} {f.price:>8}")
        print(f"  💰 Miglior prezzo: {cheapest.price}")

        msg_lines.append(f"{label} — da *{cheapest.price}*")
        for f in flights:
            msg_lines.append(f"  `{f.departure}→{f.arrival}`  {f.flight_number}  {f.price}")

    send_telegram("\n".join(msg_lines))


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--loop" in sys.argv:
        import schedule
        run_check()
        schedule.every(15).minutes.do(run_check)
        print("\n⏰ Loop ogni 15 minuti (Ctrl+C per fermare)")
        while True:
            schedule.run_pending()
            time.sleep(30)
    else:
        run_check()
