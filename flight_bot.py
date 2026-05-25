#!/usr/bin/env python3
"""
Aeroitalia Interactive Flight Bot
Guided form-based search via Telegram ConversationHandler.
"""

from __future__ import annotations
import re
import os
import json
import time
import hashlib
import asyncio
import requests
import logging
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters,
)
from playwright.sync_api import sync_playwright

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8953071582:AAHlnlWZmAnVsA2ueJFEK-_6ZJFzAv06JAQ",
)

# ─── Conversation states ───────────────────────────────────────────────────────
(
    CHOOSE_AIRLINE,
    CHOOSE_TRIP_TYPE,
    CHOOSE_MODE,
    ENTER_ORIGIN,
    ENTER_DEST,
    ENTER_DATE_GO,
    ENTER_DATE_RET,
) = range(7)

# ─── Monitor persistence ──────────────────────────────────────────────────────
MONITORS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitors.json")
MONITOR_INTERVAL = 3600  # 1 hour in seconds


def load_monitors() -> dict:
    if not os.path.exists(MONITORS_FILE):
        return {}
    try:
        with open(MONITORS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Failed to load monitors: {e}")
        return {}


def save_monitors(monitors: dict) -> None:
    try:
        with open(MONITORS_FILE, "w", encoding="utf-8") as f:
            json.dump(monitors, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Failed to save monitors: {e}")


def monitor_key(user_id: int, airline: str, origin: str, dest: str, date_go: list, date_ret: Optional[list]) -> str:
    dg = "-".join(date_go)
    dr = "-".join(date_ret) if date_ret else "none"
    return f"{user_id}_{airline}_{origin}_{dest}_{dg}_{dr}"

# ─── Airlines registry (extend here for future integrations) ──────────────────
AIRLINES = {
    "aeroitalia": "Aeroitalia",
    "ryanair": "Ryanair",
    "kiwi": "Multi-compagnia (Kiwi) – scali OK",
}

# ─── Airport / date helpers ───────────────────────────────────────────────────
AIRPORT_MAP = {
    # Italia
    "LIN": "Linate",
    "MXP": "Malpensa",
    "FCO": "Fiumicino",
    "CIA": "Ciampino",
    "CAG": "Cagliari",
    "OLB": "Olbia",
    "BRI": "Bari",
    "NAP": "Napoli",
    "PMO": "Palermo",
    "CTA": "Catania",
    "VCE": "Venezia",
    "TSF": "Treviso",
    "VRN": "Verona",
    "BGY": "Bergamo",
    "TRN": "Torino",
    "GOA": "Genova",
    "BLQ": "Bologna",
    "FLR": "Firenze",
    "PSA": "Pisa",
    "BDS": "Brindisi",
    "REG": "Reggio",
    "SUF": "Lamezia",
    "AHO": "Alghero",
    "TPS": "Trapani",
    "PMF": "Parma",
    "AOI": "Ancona",
    "PEG": "Perugia",
    "PSR": "Pescara",
    "FOG": "Foggia",
    # Europa (utili per Ryanair)
    "DUB": "Dublino",
    "STN": "Londra Stansted",
    "LTN": "Londra Luton",
    "LGW": "Londra Gatwick",
    "BVA": "Parigi Beauvais",
    "CDG": "Parigi Charles de Gaulle",
    "ORY": "Parigi Orly",
    "BCN": "Barcellona",
    "MAD": "Madrid",
    "AGP": "Malaga",
    "VLC": "Valencia",
    "SVQ": "Siviglia",
    "PMI": "Palma de Mallorca",
    "BER": "Berlino",
    "MUC": "Monaco",
    "FRA": "Francoforte",
    "HHN": "Francoforte Hahn",
    "VIE": "Vienna",
    "BRU": "Bruxelles",
    "CRL": "Charleroi",
    "AMS": "Amsterdam",
    "EIN": "Eindhoven",
    "CPH": "Copenaghen",
    "ARN": "Stoccolma",
    "OSL": "Oslo",
    "HEL": "Helsinki",
    "ATH": "Atene",
    "OPO": "Porto",
    "LIS": "Lisbona",
    "FAO": "Faro",
    "BUD": "Budapest",
    "PRG": "Praga",
    "WAW": "Varsavia",
    "KRK": "Cracovia",
    "OTP": "Bucarest",
    "SOF": "Sofia",
    "MLA": "Malta",
    "TLS": "Tolosa",
    "MRS": "Marsiglia",
    "NCE": "Nizza",
    "EDI": "Edimburgo",
    "MAN": "Manchester",
    "LHR": "Londra Heathrow",
    "LCY": "Londra City",
    "ZRH": "Zurigo",
    "GVA": "Ginevra",
    "BSL": "Basilea",
    "DUS": "Dusseldorf",
    "HAM": "Amburgo",
    "TXL": "Berlino Tegel",
    "SXF": "Berlino Schonefeld",
    "STR": "Stoccarda",
    "CGN": "Colonia",
    "BHX": "Birmingham",
    "BRS": "Bristol",
    "GLA": "Glasgow",
    "NCL": "Newcastle",
    "LPL": "Liverpool",
    "EMA": "East Midlands",
    "ORK": "Cork",
    "BFS": "Belfast",
    "RIX": "Riga",
    "TLL": "Tallinn",
    "VNO": "Vilnius",
    "KEF": "Reykjavik",
    "GDN": "Danzica",
    "WMI": "Varsavia Modlin",
    "POZ": "Poznan",
    "WRO": "Wroclaw",
    "KTW": "Katowice",
    "BTS": "Bratislava",
    "TGD": "Podgorica",
    "TIA": "Tirana",
    "SKG": "Salonicco",
    "RHO": "Rodi",
    "HER": "Heraklion",
    "JTR": "Santorini",
    "JMK": "Mykonos",
    "CFU": "Corfu",
    "SKP": "Skopje",
    "TGM": "Targu Mures",
    "CLJ": "Cluj-Napoca",
    "BEG": "Belgrado",
    "ZAG": "Zagabria",
    "SPU": "Spalato",
    "DBV": "Dubrovnik",
    "PUY": "Pola",
    "LJU": "Lubiana",
    "IST": "Istanbul",
    "SAW": "Istanbul Sabiha",
    "AYT": "Antalya",
    "ADB": "Smirne",
    # Medio Oriente
    "DXB": "Dubai",
    "AUH": "Abu Dhabi",
    "DOH": "Doha",
    "AMM": "Amman",
    "TLV": "Tel Aviv",
    "BEY": "Beirut",
    "RUH": "Riyadh",
    "JED": "Gedda",
    "KWI": "Kuwait City",
    "MCT": "Muscat",
    "BAH": "Bahrein",
    "CAI": "Il Cairo",
    "HRG": "Hurghada",
    "SSH": "Sharm el-Sheikh",
    # Asia
    "BKK": "Bangkok",
    "DMK": "Bangkok Don Mueang",
    "HKT": "Phuket",
    "SIN": "Singapore",
    "KUL": "Kuala Lumpur",
    "CGK": "Giacarta",
    "DPS": "Bali",
    "MNL": "Manila",
    "HKG": "Hong Kong",
    "PEK": "Pechino",
    "PVG": "Shanghai Pudong",
    "CAN": "Canton",
    "NRT": "Tokyo Narita",
    "HND": "Tokyo Haneda",
    "KIX": "Osaka",
    "ICN": "Seoul",
    "GMP": "Seoul Gimpo",
    "TPE": "Taipei",
    "DEL": "Delhi",
    "BOM": "Mumbai",
    "BLR": "Bangalore",
    "MAA": "Chennai",
    "CCU": "Calcutta",
    "HYD": "Hyderabad",
    "KTM": "Kathmandu",
    "CMB": "Colombo",
    "MLE": "Maldive",
    # Americhe
    "JFK": "New York JFK",
    "LGA": "New York LaGuardia",
    "EWR": "Newark",
    "LAX": "Los Angeles",
    "SFO": "San Francisco",
    "ORD": "Chicago O'Hare",
    "MDW": "Chicago Midway",
    "MIA": "Miami",
    "FLL": "Fort Lauderdale",
    "MCO": "Orlando",
    "ATL": "Atlanta",
    "BOS": "Boston",
    "IAD": "Washington Dulles",
    "DCA": "Washington Reagan",
    "DFW": "Dallas Fort Worth",
    "DEN": "Denver",
    "SEA": "Seattle",
    "LAS": "Las Vegas",
    "PHX": "Phoenix",
    "IAH": "Houston",
    "DTW": "Detroit",
    "PHL": "Philadelphia",
    "MSP": "Minneapolis",
    "YYZ": "Toronto",
    "YUL": "Montreal",
    "YVR": "Vancouver",
    "MEX": "Citta del Messico",
    "CUN": "Cancun",
    "GIG": "Rio de Janeiro Galeao",
    "GRU": "San Paolo Guarulhos",
    "EZE": "Buenos Aires Ezeiza",
    "AEP": "Buenos Aires Aeroparque",
    "SCL": "Santiago del Cile",
    "LIM": "Lima",
    "BOG": "Bogota",
    "UIO": "Quito",
    "HAV": "L'Avana",
    "PUJ": "Punta Cana",
    "SJU": "San Juan",
    # Africa
    "JNB": "Johannesburg",
    "CPT": "Citta del Capo",
    "NBO": "Nairobi",
    "ADD": "Addis Abeba",
    "CMN": "Casablanca",
    "RAK": "Marrakech",
    "TUN": "Tunisi",
    "DKR": "Dakar",
    "LOS": "Lagos",
    "ACC": "Accra",
    # Oceania
    "SYD": "Sydney",
    "MEL": "Melbourne",
    "BNE": "Brisbane",
    "PER": "Perth",
    "AKL": "Auckland",
    "NAN": "Nadi",
}

# Gruppi di aeroporti per città con più scali — usati quando l'utente scrive il nome della città
CITY_GROUPS = {
    "milano": ["MXP", "LIN", "BGY"],
    "milan": ["MXP", "LIN", "BGY"],
    "roma": ["FCO", "CIA"],
    "rome": ["FCO", "CIA"],
    "londra": ["LHR", "LGW", "STN", "LTN", "LCY"],
    "london": ["LHR", "LGW", "STN", "LTN", "LCY"],
    "parigi": ["CDG", "ORY", "BVA"],
    "paris": ["CDG", "ORY", "BVA"],
    "new york": ["JFK", "LGA", "EWR"],
    "newyork": ["JFK", "LGA", "EWR"],
    "berlino": ["BER"],
    "berlin": ["BER"],
    "venezia": ["VCE", "TSF"],
    "venice": ["VCE", "TSF"],
    "francoforte": ["FRA", "HHN"],
    "frankfurt": ["FRA", "HHN"],
    "bruxelles": ["BRU", "CRL"],
    "brussels": ["BRU", "CRL"],
    "tokyo": ["NRT", "HND"],
    "osaka": ["KIX"],
    "seul": ["ICN", "GMP"],
    "seoul": ["ICN", "GMP"],
    "bangkok": ["BKK", "DMK"],
    "shanghai": ["PVG"],
    "buenos aires": ["EZE", "AEP"],
    "san paolo": ["GRU"],
    "sao paulo": ["GRU"],
    "chicago": ["ORD", "MDW"],
    "washington": ["IAD", "DCA"],
    "houston": ["IAH"],
    "miami": ["MIA", "FLL"],
    "los angeles": ["LAX"],
    "istanbul": ["IST", "SAW"],
    "varsavia": ["WAW", "WMI"],
    "warsaw": ["WAW", "WMI"],
    "dubai": ["DXB"],
    "doha": ["DOH"],
    "amsterdam": ["AMS"],
    "barcellona": ["BCN"],
    "barcelona": ["BCN"],
    "madrid": ["MAD"],
    "lisbona": ["LIS"],
    "lisbon": ["LIS"],
    "dublino": ["DUB"],
    "dublin": ["DUB"],
    "vienna": ["VIE"],
    "praga": ["PRG"],
    "prague": ["PRG"],
    "atene": ["ATH"],
    "athens": ["ATH"],
}

MONTH_MAP = {
    "01": "gen", "02": "feb", "03": "mar", "04": "apr",
    "05": "mag", "06": "giu", "07": "lug", "08": "ago",
    "09": "set", "10": "ott", "11": "nov", "12": "dic",
}

ITALIAN_MONTHS_FULL = {
    "gennaio": "gen", "febbraio": "feb", "marzo": "mar", "aprile": "apr",
    "maggio": "mag", "giugno": "giu", "luglio": "lug", "agosto": "ago",
    "settembre": "set", "ottobre": "ott", "novembre": "nov", "dicembre": "dic",
}


def airport_search_term(code_or_name: str) -> str:
    upper = code_or_name.upper()
    return AIRPORT_MAP.get(upper, code_or_name)


def airport_iatas(code_or_name: str) -> list[str]:
    """Risolve input utente in LISTA di codici IATA. Per città multi-aeroporto restituisce tutti."""
    s = code_or_name.strip()
    s_lower = s.lower()
    # 1) Codice IATA esatto (3 lettere)
    if len(s) == 3 and s.isalpha():
        return [s.upper()]
    # 2) Gruppo città (Milano, Londra, ...)
    if s_lower in CITY_GROUPS:
        return CITY_GROUPS[s_lower]
    # 3) Match parziale nei nomi città dell'AIRPORT_MAP
    matches = []
    for iata, city in AIRPORT_MAP.items():
        city_l = city.lower()
        if city_l == s_lower or s_lower in city_l or city_l in s_lower:
            matches.append(iata)
    if matches:
        return matches
    # 4) Fallback: l'input come è (uppercase)
    return [s.upper()]


def airport_iata(code_or_name: str) -> str:
    """Primo IATA dalla lista — per scraper che accettano un solo codice (Ryanair URL)."""
    return airport_iatas(code_or_name)[0]


def parse_date(date_str: str) -> tuple[str, str, str]:
    date_str = date_str.strip().replace("-", "/")
    parts = date_str.split("/")
    if not parts[0].isdigit():
        raise ValueError("invalid date")
    day = parts[0].zfill(2)
    if not (1 <= int(day) <= 31):
        raise ValueError("invalid day")
    month = parts[1].zfill(2) if len(parts) > 1 else str(datetime.now().month).zfill(2)
    year = parts[2] if len(parts) > 2 else str(datetime.now().year)
    return day, MONTH_MAP.get(month, "mag"), year


def parse_month_or_date(text: str):
    """Returns ('month', month_it, year) o ('date', day, month_it, year), o None se non valido."""
    text = text.strip().lower()
    # MM/YYYY or MM-YYYY
    m = re.match(r"^(\d{1,2})[/-](\d{4})$", text)
    if m:
        mn = m.group(1).zfill(2)
        if mn in MONTH_MAP:
            return ("month", MONTH_MAP[mn], m.group(2))
    # MonthName [year]
    tokens = text.split()
    if tokens:
        first = tokens[0]
        month_it = ITALIAN_MONTHS_FULL.get(first)
        if not month_it and first in MONTH_MAP.values():
            month_it = first
        if month_it:
            year = (
                tokens[1]
                if len(tokens) > 1 and tokens[1].isdigit() and len(tokens[1]) == 4
                else str(datetime.now().year)
            )
            return ("month", month_it, year)
    # Else: date
    try:
        day, m_it, year = parse_date(text)
        return ("date", day, m_it, year)
    except Exception:
        return None


def month_num(month_it: str) -> str:
    for k, v in MONTH_MAP.items():
        if v == month_it:
            return k
    return "05"


def fmt_date(day: str, month_it: str, year: str) -> str:
    return f"{day}/{month_num(month_it)}/{year}"


def months_ahead(month_it: str, year: str) -> int:
    """Quante volte navigare avanti nel calendario dalla data odierna."""
    now = datetime.now()
    target_m = int(month_num(month_it))
    target_y = int(year)
    return max(0, (target_y - now.year) * 12 + (target_m - now.month))


# ─── Data model ───────────────────────────────────────────────────────────────
@dataclass
class Flight:
    departure: str  # ora di partenza HH:MM
    arrival: str    # ora di arrivo HH:MM
    flight_number: str
    duration: str
    fare_class: str
    price: str
    stops: list = None             # codici IATA degli scali (es. ['BCN']); vuoto/None per volo diretto
    origin_airport: str = ""       # IATA aeroporto di partenza (es. "MXP")
    dest_airport: str = ""         # IATA aeroporto di arrivo (es. "DXB")
    segments: list = None          # lista dict per ogni tratta: {carrier, code, origin, dest, date}


# ─── Scraper ──────────────────────────────────────────────────────────────────
def scrape_flights(origin_term: str, dest_term: str, day: str, month_it: str, year: str) -> List[Flight]:
    flights: List[Flight] = []
    # IATA dell'aeroporto (per popolare origin_airport/dest_airport dei Flight)
    origin_iata_guess = airport_iata(origin_term)
    dest_iata_guess = airport_iata(dest_term)

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

        page.locator("input[placeholder='Selezionare la partenza']").click()
        page.keyboard.type(origin_term, delay=70)
        time.sleep(1.2)
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        time.sleep(0.3)

        page.locator("input[placeholder='Selezionare la destinazione']").click()
        page.keyboard.type(dest_term, delay=70)
        time.sleep(1.2)
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        time.sleep(0.3)

        page.locator("input[value='Selezionare le date']").first.click(force=True)
        time.sleep(1.5)

        page.locator("text=Volo di sola andata").first.click(force=True)
        time.sleep(0.3)

        nav_steps = months_ahead(month_it, year)
        for _ in range(nav_steps):
            page.mouse.click(1444, 328)
            time.sleep(0.3)

        # Wait for calendar prices to finish loading (spinners → €)
        try:
            page.wait_for_function(
                r"""() => {
                    for (const el of document.querySelectorAll('span, div')) {
                        const t = (el.textContent || '').trim();
                        const rect = el.getBoundingClientRect();
                        if (rect.width < 40 || rect.height < 30) continue;
                        if (t.includes('€') && /^\d/.test(t)) return true;
                    }
                    return false;
                }""",
                timeout=10000,
            )
        except Exception:
            time.sleep(3)

        clicked = page.evaluate(r"""(day) => {
            // Left panel = x < half viewport width (1920px viewport → 960)
            const panelBoundary = window.innerWidth / 2;
            for (const el of document.querySelectorAll('span, div')) {
                const text = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                if (rect.width < 40 || rect.height < 30) continue;
                if (rect.x >= panelBoundary) continue;
                if (!text.startsWith(day)) continue;
                if (!text.includes('€') && !text.toLowerCase().includes('sold')) continue;
                el.click();
                return {ok: true, text: text.substring(0, 30)};
            }
            return {ok: false, debug: 'day not found in left panel'};
        }""", str(int(day)))

        if not clicked.get("ok"):
            browser.close()
            return flights

        sold_out_day = "sold" in (clicked.get("text", "")).lower()
        time.sleep(0.2)

        try:
            page.locator("button:has-text('Fine')").first.click(force=True)
        except Exception:
            pass
        time.sleep(0.2)

        if sold_out_day:
            browser.close()
            return []

        page.locator("button:has-text('Ricerca')").first.click(force=True)

        try:
            page.wait_for_selector("text=Volo diretto", timeout=25000)
        except Exception:
            pass
        time.sleep(0.5)

        for _ in range(3):
            page.evaluate("""() => {
                window.scrollTo(0, document.body.scrollHeight);
                document.querySelectorAll('ion-content').forEach(el => {
                    const inner = el.shadowRoot?.querySelector('.inner-scroll');
                    if (inner) inner.scrollTop = inner.scrollHeight;
                });
            }""")
            time.sleep(0.3)

        body = page.locator("body").text_content() or ""
        browser.close()

    day_d = str(int(day))  # strip leading zero: "08" → "8", "28" → "28"
    if f"{day_d} {month_it} {year}" not in body:
        return flights

    pattern = (
        rf'(\d{{2}}:\d{{2}}){day_d} {month_it} {year}[\w\s()]+?'
        r'(1 ora \d+min)Volo diretto(XZ\d+)'
        rf'(\d{{2}}:\d{{2}}){day_d} {month_it} {year}[\w\s()]*'
        r'([A-Z][a-z]+)(\d+,\d{2})\s*€'
    )
    date_iso_ai = f"{year}-{month_num(month_it)}-{day.zfill(2)}"
    for m in re.finditer(pattern, body):
        fn = m.group(3)
        flights.append(Flight(
            departure=m.group(1),
            arrival=m.group(4),
            flight_number=fn,
            duration=m.group(2),
            fare_class=m.group(5),
            price=f"{m.group(6)}€",
            origin_airport=origin_iata_guess,
            dest_airport=dest_iata_guess,
            segments=[{
                "carrier": "XZ", "carrier_name": "Aeroitalia",
                "code": fn.replace("XZ", ""),
                "origin": origin_iata_guess, "dest": dest_iata_guess,
                "date": date_iso_ai,
                "dep_time": m.group(1), "arr_time": m.group(4),
            }],
        ))

    if not flights:
        city_from = origin_term.split()[0]
        city_to = dest_term.split()[0]
        pattern2 = (
            rf'(\d{{2}}:\d{{2}}){day_d} {month_it} {year}{city_from}'
            r'(1 ora \d+min)Volo diretto(XZ\d+)'
            rf'(\d{{2}}:\d{{2}}){day_d} {month_it} {year}{city_to}'
            r'([A-Za-z]+)(\d+,\d{2})\s*€'
        )
        for m in re.finditer(pattern2, body):
            flights.append(Flight(
                departure=m.group(1),
                arrival=m.group(4),
                flight_number=m.group(3),
                duration=m.group(2),
                origin_airport=origin_iata_guess,
                dest_airport=dest_iata_guess,
                fare_class=m.group(5),
                price=f"{m.group(6)}€",
            ))

    return flights


# ─── Scraper Ryanair ──────────────────────────────────────────────────────────
def scrape_flights_ryanair(origin_iata: str, dest_iata: str, day: str, month_it: str, year: str) -> List[Flight]:
    flights: List[Flight] = []
    date_str = f"{year}-{month_num(month_it)}-{day}"
    url = (
        "https://www.ryanair.com/it/it/trip/flights/select"
        f"?adults=1&teens=0&children=0&infants=0"
        f"&dateOut={date_str}&isReturn=false"
        f"&originIata={origin_iata}&destinationIata={dest_iata}"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="it-IT",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(15000)

        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        try:
            page.locator('button:has-text("No, grazie")').first.click(timeout=4000)
        except Exception:
            pass

        try:
            page.wait_for_selector("text=/FR \\d+/", timeout=15000)
        except Exception:
            browser.close()
            return flights

        time.sleep(0.8)
        body = page.locator("body").text_content() or ""
        browser.close()

    pattern = re.compile(
        r'(\d{2}:\d{2})\s+([\w\s]+?)\s+(FR\s*\d+)'
        r'\s+(\d+\s*h\s*\d+\s*m)'
        r'\s+(\d{2}:\d{2})\s+([\w\s]+?)'
        r'\s+Tariffa\s+\w+\s+(\d+,\d{2})\s*€'
        r'(?:\s*\n?\s*(\d+,\d{2})\s*€)?'
    )
    date_iso_ry = f"{year}-{month_num(month_it)}-{day.zfill(2)}"
    for m in pattern.finditer(body):
        price = m.group(8) if m.group(8) else m.group(7)
        fn = m.group(3).replace(" ", "")
        flights.append(Flight(
            departure=m.group(1),
            arrival=m.group(5),
            flight_number=fn,
            duration=m.group(4).replace(" ", "").replace("h", "h ").replace("m", "min"),
            fare_class="Basic",
            price=f"{price}€",
            origin_airport=origin_iata,
            dest_airport=dest_iata,
            segments=[{
                "carrier": "FR", "carrier_name": "Ryanair",
                "code": fn.replace("FR", ""),
                "origin": origin_iata, "dest": dest_iata,
                "date": date_iso_ry,
                "dep_time": m.group(1), "arr_time": m.group(5),
            }],
        ))

    return flights


# ─── Ryanair: disponibilità mensile (API pubblica) ────────────────────────────
WEEKDAY_IT = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def ryanair_month_fares(origin_iata: str, dest_iata: str, month_it: str, year: str) -> list[dict]:
    """Restituisce la lista dei giorni del mese con prezzo/disponibilità via API pubblica Ryanair."""
    first_day = f"{year}-{month_num(month_it)}-01"
    url = f"https://www.ryanair.com/api/farfnd/v4/oneWayFares/{origin_iata}/{dest_iata}/cheapestPerDay"
    try:
        r = requests.get(
            url,
            params={"outboundMonthOfDate": first_day, "currency": "EUR"},
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        return r.json().get("outbound", {}).get("fares", [])
    except Exception as e:
        logging.warning(f"ryanair_month_fares error: {e}")
        return []


def ryanair_nearest_days(origin_iata: str, dest_iata: str, month_it: str, year: str, target_day: str) -> tuple:
    """Restituisce (prev, next) come tuple (day, weekday) o None, all'interno del mese."""
    days = ryanair_available_days(origin_iata, dest_iata, month_it, year)
    target = target_day.zfill(2)
    prev_day = None
    next_day = None
    for day, wd in days:
        if day < target:
            prev_day = (day, wd)
        elif day > target and next_day is None:
            next_day = (day, wd)
            break
    return prev_day, next_day


def ryanair_available_days(origin_iata: str, dest_iata: str, month_it: str, year: str) -> list[tuple[str, str]]:
    """Restituisce [(day_num, weekday_short)] per i giorni con voli Ryanair nel mese."""
    fares = ryanair_month_fares(origin_iata, dest_iata, month_it, year)
    result = []
    for f in fares:
        if f.get("unavailable") or f.get("soldOut"):
            continue
        if f.get("price", {}).get("value") is None:
            continue
        day_iso = f["day"]
        day_num = day_iso.split("-")[-1]
        try:
            dt = datetime.fromisoformat(day_iso)
            wd = WEEKDAY_IT[dt.weekday()]
        except Exception:
            wd = "?"
        result.append((day_num, wd))
    return result


def aeroitalia_available_days(origin_term: str, dest_term: str, month_it: str, year: str) -> list[tuple[str, str]]:
    """Apre il calendario Aeroitalia, naviga al mese e raccoglie i giorni con prezzi (= disponibili)."""
    import calendar as cal
    month_n = int(month_num(month_it))
    year_n = int(year)
    first_weekday = datetime(year_n, month_n, 1).weekday()  # 0=lun
    days_in_month = cal.monthrange(year_n, month_n)[1]

    cells_data = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="it-IT",
            ignore_https_errors=True,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()
        page.set_default_timeout(15000)
        page.goto("https://book.aeroitalia.com/", wait_until="networkidle", timeout=30000)

        page.locator("input[placeholder='Selezionare la partenza']").click()
        page.keyboard.type(origin_term, delay=70); time.sleep(1.2)
        page.keyboard.press("ArrowDown"); page.keyboard.press("Enter"); time.sleep(0.3)
        page.locator("input[placeholder='Selezionare la destinazione']").click()
        page.keyboard.type(dest_term, delay=70); time.sleep(1.2)
        page.keyboard.press("ArrowDown"); page.keyboard.press("Enter"); time.sleep(0.3)

        page.locator("input[value='Selezionare le date']").first.click(force=True); time.sleep(1.5)
        page.locator("text=Volo di sola andata").first.click(force=True); time.sleep(0.3)

        for _ in range(months_ahead(month_it, year)):
            page.mouse.click(1444, 328); time.sleep(0.3)

        try:
            page.wait_for_function(
                r"""() => {
                    for (const el of document.querySelectorAll('span, div')) {
                        const t = (el.textContent || '').trim();
                        const r = el.getBoundingClientRect();
                        if (r.width < 40 || r.height < 30) continue;
                        if (t.includes('€') && /^\d/.test(t)) return true;
                    }
                    return false;
                }""",
                timeout=10000,
            )
        except Exception:
            time.sleep(3)

        cells_data = page.evaluate(r"""() => {
            const found = [];
            const seen = new Set();
            const panelBoundary = window.innerWidth / 2;
            for (const el of document.querySelectorAll('span, div')) {
                const t = (el.textContent || '').trim();
                const r = el.getBoundingClientRect();
                if (r.width < 40 || r.height < 30) continue;
                if (r.width > 90 || r.height > 80) continue;  // skip row containers
                if (r.x >= panelBoundary) continue;
                if (!t.includes('€') && !t.toLowerCase().includes('sold')) continue;
                if (!/^\d/.test(t)) continue;
                const key = Math.round(r.x) + '_' + Math.round(r.y);
                if (seen.has(key)) continue;
                seen.add(key);
                found.push({x: Math.round(r.x), y: Math.round(r.y), text: t.substring(0, 30)});
            }
            return found;
        }""")
        browser.close()

    if not cells_data:
        return []

    # Map cells to days using (row, col) and first_weekday
    # Sort by y, group rows
    cells_data.sort(key=lambda c: (c["y"], c["x"]))
    row_ys = []
    for c in cells_data:
        if not row_ys or abs(c["y"] - row_ys[-1]) > 20:
            row_ys.append(c["y"])

    col_xs = sorted({c["x"] for c in cells_data})  # up to 7 column positions

    available = []
    for c in cells_data:
        # find row index
        row_idx = min(range(len(row_ys)), key=lambda i: abs(row_ys[i] - c["y"]))
        # find col index
        col_idx = min(range(len(col_xs)), key=lambda i: abs(col_xs[i] - c["x"]))
        day = row_idx * 7 + col_idx + 1 - first_weekday
        if 1 <= day <= days_in_month:
            wd = WEEKDAY_IT[col_idx]
            is_sold = "sold" in c["text"].lower()
            if not is_sold:
                available.append((str(day).zfill(2), wd))
    # de-duplicate & sort
    seen_days = set()
    unique = []
    for d, w in sorted(available, key=lambda x: int(x[0])):
        if d not in seen_days:
            seen_days.add(d)
            unique.append((d, w))
    return unique


# ─── Kiwi.com (multi-compagnia, voli con scali) ────────────────────────────────
KIWI_GRAPHQL_URL = "https://api.skypicker.com/umbrella/v2/graphql?featureName=SearchOneWayItinerariesQuery"

KIWI_QUERY = """query SearchOneWayItinerariesQuery($search: SearchOnewayInput, $filter: ItinerariesFilterInput, $options: ItinerariesOptionsInput) {
  onewayItineraries(search: $search, filter: $filter, options: $options) {
    __typename
    ... on AppError { error: message }
    ... on Itineraries {
      itineraries {
        ... on ItineraryOneWay {
          duration
          price { amount }
          sector {
            sectorSegments {
              segment {
                source { localTime station { code name } }
                destination { localTime station { code name } }
                duration
                type
                carrier { code name }
                code
              }
            }
          }
        }
      }
    }
  }
}"""


def _kiwi_headers() -> dict:
    import uuid as _uuid
    return {
        "content-type": "application/json",
        "kw-skypicker-visitor-uniqid": str(_uuid.uuid4()),
        "kw-x-rand-id": hashlib.sha1(str(time.time()).encode()).hexdigest(),
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "origin": "https://www.kiwi.com",
        "referer": "https://www.kiwi.com/",
    }


def _kiwi_variables(origin_iata, dest_iata, date_iso: str, limit: int = 10) -> dict:
    # Accetta sia singolo IATA (str) sia lista
    if isinstance(origin_iata, str):
        origin_iata = [origin_iata]
    if isinstance(dest_iata, str):
        dest_iata = [dest_iata]
    return {
        "search": {
            "itinerary": {
                "source": {"ids": [f"Station:airport:{c}" for c in origin_iata]},
                "destination": {"ids": [f"Station:airport:{c}" for c in dest_iata]},
                "outboundDepartureDate": {"start": f"{date_iso}T00:00:00", "end": f"{date_iso}T23:59:59"},
            },
            "passengers": {"adults": 1, "children": 0, "infants": 0, "adultsHoldBags": [0], "adultsHandBags": [0], "childrenHoldBags": [], "childrenHandBags": []},
            "cabinClass": {"cabinClass": "ECONOMY", "applyMixedClasses": False},
        },
        "filter": {
            "allowChangeInboundDestination": True, "allowChangeInboundSource": True,
            "allowDifferentStationConnection": True, "enableSelfTransfer": True,
            "enableThrowAwayTicketing": True, "enableTrueHiddenCity": True,
            "transportTypes": ["FLIGHT"], "flightsApiLimit": 25, "limit": limit,
        },
        "options": {
            "sortBy": "QUALITY", "mergePriceDiffRule": "INCREASED",
            "currency": "eur", "locale": "en", "market": "it",
            "partner": "skypicker", "partnerMarket": "it", "affilID": "skypicker",
            "storeSearch": False, "searchStrategy": "REDUCED",
        },
    }


def scrape_flights_kiwi(origin_iata, dest_iata, day: str, month_it: str, year: str) -> List[Flight]:
    date_iso = f"{year}-{month_num(month_it)}-{day.zfill(2)}"
    try:
        r = requests.post(
            KIWI_GRAPHQL_URL, headers=_kiwi_headers(),
            json={"query": KIWI_QUERY, "variables": _kiwi_variables(origin_iata, dest_iata, date_iso, limit=15)},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logging.warning(f"Kiwi scrape error {origin_iata}-{dest_iata} {date_iso}: {e}")
        return []

    if "errors" in data:
        logging.warning(f"Kiwi GraphQL errors: {data['errors']}")
        return []

    itin_list = (
        data.get("data", {}).get("onewayItineraries", {}).get("itineraries", []) or []
    )
    flights = []
    for it in itin_list:
        try:
            segs = it["sector"]["sectorSegments"]
            first_seg = segs[0]["segment"]
            last_seg = segs[-1]["segment"]
            dep = first_seg["source"]["localTime"][11:16]
            arr = last_seg["destination"]["localTime"][11:16]
            origin_code = first_seg["source"]["station"]["code"]
            dest_code = last_seg["destination"]["station"]["code"]
            # Costruisci stops mostrando il self-transfer: se arrivi a LGW ma riparti da STN, indica entrambi
            stops = []
            for i in range(len(segs) - 1):
                arr_code = segs[i]["segment"]["destination"]["station"]["code"]
                next_dep = segs[i + 1]["segment"]["source"]["station"]["code"]
                if arr_code == next_dep:
                    stops.append(arr_code)
                else:
                    stops.append(f"{arr_code}✈{next_dep}")  # cambio aeroporto
            flight_no = "+".join(f"{s['segment']['carrier']['code']}{s['segment']['code']}" for s in segs)
            carriers = ", ".join(sorted({s["segment"]["carrier"]["name"] for s in segs}))
            total_min = it["duration"] // 60
            duration_str = f"{total_min // 60}h {total_min % 60:02d}min"
            price = float(it["price"]["amount"])
            price_str = f"{price:.2f}".replace(".", ",") + "€"
            segments_info = [{
                "carrier": s["segment"]["carrier"]["code"],
                "carrier_name": s["segment"]["carrier"]["name"],
                "code": s["segment"]["code"],
                "origin": s["segment"]["source"]["station"]["code"],
                "dest": s["segment"]["destination"]["station"]["code"],
                "date": s["segment"]["source"]["localTime"][:10],  # YYYY-MM-DD
                "dep_time": s["segment"]["source"]["localTime"][11:16],
                "arr_time": s["segment"]["destination"]["localTime"][11:16],
            } for s in segs]
            flights.append(Flight(
                departure=dep, arrival=arr,
                flight_number=flight_no, duration=duration_str,
                fare_class=carriers, price=price_str, stops=stops,
                origin_airport=origin_code, dest_airport=dest_code,
                segments=segments_info,
            ))
        except Exception as e:
            logging.warning(f"Kiwi parse error: {e}")
    return flights


def kiwi_available_days(origin_iata, dest_iata, month_it: str, year: str) -> list[tuple[str, str]]:
    """Per ogni giorno del mese, prova una query (rapida) e raccogli quelli con voli."""
    import calendar as cal
    month_n = int(month_num(month_it))
    year_n = int(year)
    days_in_month = cal.monthrange(year_n, month_n)[1]
    result = []
    for d in range(1, days_in_month + 1):
        date_iso = f"{year}-{str(month_n).zfill(2)}-{str(d).zfill(2)}"
        try:
            r = requests.post(
                KIWI_GRAPHQL_URL, headers=_kiwi_headers(),
                json={"query": KIWI_QUERY, "variables": _kiwi_variables(origin_iata, dest_iata, date_iso, limit=1)},
                timeout=10,
            )
            if r.status_code != 200:
                continue
            data = r.json()
            itin = data.get("data", {}).get("onewayItineraries", {}).get("itineraries", []) or []
            if itin:
                wd = WEEKDAY_IT[datetime(year_n, month_n, d).weekday()]
                result.append((str(d).zfill(2), wd))
        except Exception:
            continue
    return result


def kiwi_nearest_days(origin_iata, dest_iata, month_it: str, year: str, target_day: str) -> tuple:
    days = kiwi_available_days(origin_iata, dest_iata, month_it, year)
    target = target_day.zfill(2)
    prev_day = None
    next_day = None
    for day, wd in days:
        if day < target:
            prev_day = (day, wd)
        elif day > target and next_day is None:
            next_day = (day, wd)
            break
    return prev_day, next_day


def format_available_days(days: list[tuple[str, str]], origin: str, dest: str, month_it: str, year: str) -> str:
    lines = [f"📅 *{month_it.capitalize()} {year} — {origin} → {dest}*\n"]
    if not days:
        lines.append("🚫 _Nessun volo disponibile in questo mese_")
        return "\n".join(lines)
    lines.append(f"✅ *Giorni disponibili ({len(days)}):*")
    for day_num, wd in days:
        lines.append(f"  `{wd} {day_num}`")
    return "\n".join(lines)


# ─── Pagine ufficiali compagnie aeree ─────────────────────────────────────────
def _ry_url(o, d, date_iso):
    return ("https://www.ryanair.com/it/it/trip/flights/select"
            f"?adults=1&teens=0&children=0&infants=0&dateOut={date_iso}&isReturn=false"
            f"&originIata={o}&destinationIata={d}")

def _ai_url(o, d, date_iso):
    return ("https://book.aeroitalia.com/select-flights/"
            f"?Culture=it-IT&AdultCount=1&O1={o}&D1={d}&DD1={date_iso}")

def _ej_url(o, d, date_iso):
    return ("https://www.easyjet.com/it/cerca-volo/lista-prezzi"
            f"?dep={o}&dest={d}&depDate={date_iso}&isReturn=false&adult=1")

def _vy_url(o, d, date_iso):
    return ("https://tickets.vueling.com/ScheduleSelectNew.aspx"
            f"?CULTURE=it-IT&Trip=OW&O1={o}&D1={d}&DD1={date_iso}&ADT=1")

def _wz_url(o, d, date_iso):
    return ("https://wizzair.com/it-it/voli/seleziona-volo/lookup"
            f"?departureStation={o}&arrivalStation={d}&departureDate={date_iso}&returnDate=&adultCount=1")

def _fz_url(o, d, date_iso):
    return ("https://www.flydubai.com/it/booking/flight-search"
            f"?origin={o}&destination={d}&departureDate={date_iso}&adultsCount=1&tripType=O")

def _qr_url(o, d, date_iso):
    return ("https://booking.qatarairways.com/nsp/views/showBookingSearch.action"
            f"?bookingClass=E&tripType=O&fromStation={o}&toStation={d}&departingDate={date_iso}&adults=1&children=0&infants=0")

def _az_url(o, d, date_iso):
    return ("https://www.ita-airways.com/it_it/booking/buy-flight-tickets.html"
            f"?o={o}&d={d}&dt={date_iso}&adt=1&trip=OW")

def _w6_url(o, d, date_iso):  # alias W6 = Wizz Air
    return _wz_url(o, d, date_iso)

def _ei_url(o, d, date_iso):  # Aer Lingus
    # formato "DD-MM-YYYY"
    yyyy, mm, dd = date_iso.split("-")
    return f"https://book.aerlingus.com/lp/iba?o={o}&d={d}&dt={dd}-{mm}-{yyyy}&t=1&n=1&y=0"

def _lh_url(o, d, date_iso):  # Lufthansa
    return ("https://www.lufthansa.com/it/it/flight-search"
            f"?bookingType=oneWayTrip&travelers=1&travelClass=Y&from={o}&to={d}&departureDate={date_iso}")

def _af_url(o, d, date_iso):  # Air France
    return f"https://www.airfrance.it/IT/it/local/process/standardbooking/SearchAirRouteAndDate.do?originAirportCode={o}&destinationAirportCode={d}&outboundDate={date_iso}&adults=1"

def _kl_url(o, d, date_iso):  # KLM
    return f"https://www.klm.it/search/offers?type=ONEWAY&from={o}&to={d}&date={date_iso}&adt=1"

def _ba_url(o, d, date_iso):  # British Airways
    yyyy, mm, dd = date_iso.split("-")
    return f"https://www.britishairways.com/travel/book/public/it_it?eId=199001&from={o}&to={d}&depDate={dd}/{mm}/{yyyy}&adults=1&CabinCode=M&IsOneWay=true"

def _tp_url(o, d, date_iso):  # TAP Portugal
    return f"https://book.flytap.com/booking/flights/avail?origin={o}&destination={d}&departure={date_iso}&adults=1&type=ONE_WAY"

def _ib_url(o, d, date_iso):  # Iberia
    yyyy, mm, dd = date_iso.split("-")
    return f"https://www.iberia.com/it/?from={o}&to={d}&dep_date={dd}/{mm}/{yyyy}&trip=O&adults=1"

def _tk_url(o, d, date_iso):  # Turkish Airlines
    yyyy, mm, dd = date_iso.split("-")
    return f"https://www.turkishairlines.com/it-it/flights/booking/index.html?origin={o}&destination={d}&departureDate={yyyy}-{mm}-{dd}&tripType=oneWay&adults=1"

def _ek_url(o, d, date_iso):  # Emirates
    return f"https://www.emirates.com/it/italian/book-a-flight/?originCity={o}&destinationCity={d}&departureDate={date_iso}&tripType=OW&adults=1"

def _a3_url(o, d, date_iso):  # Aegean
    return f"https://en.aegeanair.com/flights-from-to/?origin={o}&destination={d}&departureDate={date_iso}&tripType=ONEWAY&adults=1"

def _lo_url(o, d, date_iso):  # LOT Polish
    return f"https://www.lot.com/it/it/?origin={o}&destination={d}&departureDate={date_iso}&adults=1&tripType=OW"

def _ew_url(o, d, date_iso):  # Eurowings
    return f"https://www.eurowings.com/it/booking/preview.html?origin={o}&destination={d}&departureDate={date_iso}&adults=1&type=ONEWAY"

def _os_url(o, d, date_iso):  # Austrian
    return f"https://www.austrian.com/it-it/Flights?origin={o}&destination={d}&departureDate={date_iso}&adults=1&tripType=OW"

def _lx_url(o, d, date_iso):  # Swiss
    return f"https://www.swiss.com/it/it/Book/Flight?origin={o}&destination={d}&departureDate={date_iso}&adults=1&tripType=OW"

def _sn_url(o, d, date_iso):  # Brussels Airlines
    return f"https://www.brusselsairlines.com/it/it/flights?origin={o}&destination={d}&departureDate={date_iso}&adults=1&tripType=OW"

def _ay_url(o, d, date_iso):  # Finnair
    return f"https://www.finnair.com/it/it/book/flights?origin={o}&destination={d}&departureDate={date_iso}&adults=1&tripType=ONEWAY"

def _ms_url(o, d, date_iso):  # EgyptAir
    return f"https://www.egyptair.com/it-it/flights/Pages/default.aspx?from={o}&to={d}&date={date_iso}&adults=1&trip=oneway"

def _ey_url(o, d, date_iso):  # Etihad
    return f"https://www.etihad.com/it-it/book/booking?origin={o}&destination={d}&departureDate={date_iso}&adults=1&tripType=ONEWAY"

# Mappa: codice IATA compagnia → builder URL deep-link (origin, dest, date_iso)
AIRLINE_DEEP_LINKS = {
    # Ryanair group (Ireland, UK, Buzz/Sun, Malta Air operational)
    "FR": _ry_url,    # Ryanair
    "RK": _ry_url,    # Ryanair UK
    "RYR": _ry_url,   # Ryanair codice ICAO operativo
    "BUZ": _ry_url,   # Buzz (Ryanair Sun, operativo)
    "MAY": _ry_url,   # Malta Air (operativo per Ryanair)
    # Aeroitalia
    "XZ": _ai_url,
    # easyJet (mainline + UK + Switzerland operate sotto easyjet.com)
    "U2": _ej_url,
    "EZY": _ej_url,
    "EJU": _ej_url,
    "DS": _ej_url,    # easyJet Switzerland
    # Vueling
    "VY": _vy_url,
    "VLG": _vy_url,
    # Wizz Air (mainline + UK + Malta + Abu Dhabi operano via wizzair.com)
    "W6": _w6_url,
    "WZZ": _w6_url,
    "W9": _w6_url,    # Wizz Air Malta
    "5W": _w6_url,    # Wizz Air Abu Dhabi
    "W4": _w6_url,    # variante operativa Wizz
    # FlyDubai
    "FZ": _fz_url,
    "FDB": _fz_url,
    # Qatar Airways
    "QR": _qr_url,
    "QTR": _qr_url,
    # ITA Airways
    "AZ": _az_url,
    "ITY": _az_url,
    # Aer Lingus
    "EI": _ei_url,
    "EIN": _ei_url,
    # Lufthansa group
    "LH": _lh_url,
    "DLH": _lh_url,
    "OS": _os_url,    # Austrian
    "LX": _lx_url,    # Swiss
    "SN": _sn_url,    # Brussels
    "EW": _ew_url,    # Eurowings
    # Air France-KLM
    "AF": _af_url,
    "KL": _kl_url,
    # British Airways
    "BA": _ba_url,
    "BAW": _ba_url,
    # TAP Portugal
    "TP": _tp_url,
    "TAP": _tp_url,
    # Iberia
    "IB": _ib_url,
    "IBE": _ib_url,
    # Turkish Airlines
    "TK": _tk_url,
    "THY": _tk_url,
    # Emirates / Etihad / Aegean / LOT
    "EK": _ek_url,
    "EY": _ey_url,
    "A3": _a3_url,
    "LO": _lo_url,
    # Finnair / EgyptAir
    "AY": _ay_url,
    "MS": _ms_url,
}

# Mappa: codice → homepage ufficiale (fallback se non c'è deep link)
AIRLINE_HOMEPAGES = {
    "EI": "https://www.aerlingus.com/",
    "EK": "https://www.emirates.com/",
    "EY": "https://www.etihad.com/",
    "TK": "https://www.turkishairlines.com/",
    "LH": "https://www.lufthansa.com/",
    "AF": "https://www.airfrance.it/",
    "KL": "https://www.klm.it/",
    "BA": "https://www.britishairways.com/",
    "PC": "https://www.flypgs.com/",
    "MS": "https://www.egyptair.com/",
    "RO": "https://www.tarom.ro/",
    "CY": "https://www.cyprusairways.com/",
    "SN": "https://www.brusselsairlines.com/",
    "OS": "https://www.austrian.com/",
    "LX": "https://www.swiss.com/",
    "IB": "https://www.iberia.com/",
    "TP": "https://www.flytap.com/",
    "AY": "https://www.finnair.com/",
    "SK": "https://www.flysas.com/",
    "DY": "https://www.norwegian.com/",
    "BT": "https://www.airbaltic.com/",
    "OK": "https://www.csa.cz/",
    "RJ": "https://www.rj.com/",
    "ME": "https://www.mea.com.lb/",
    "MU": "https://www.ceair.com/",
    "CA": "https://www.airchina.com/",
    "CZ": "https://www.csair.com/",
    "NH": "https://www.ana.co.jp/",
    "JL": "https://www.jal.co.jp/",
    "SQ": "https://www.singaporeair.com/",
    "CX": "https://www.cathaypacific.com/",
    "AA": "https://www.aa.com/",
    "UA": "https://www.united.com/",
    "DL": "https://www.delta.com/",
    "AC": "https://www.aircanada.com/",
    "AS": "https://www.alaskaair.com/",
    "B6": "https://www.jetblue.com/",
    "A3": "https://en.aegeanair.com/",
    "LO": "https://www.lot.com/",
    "EW": "https://www.eurowings.com/",
    "HV": "https://www.transavia.com/",
    "TO": "https://www.transavia.com/",
    "F9": "https://www.flyfrontier.com/",
    "NK": "https://www.spirit.com/",
    "WN": "https://www.southwest.com/",
    "G4": "https://www.allegiantair.com/",
    "VS": "https://www.virginatlantic.com/",
    "AT": "https://www.royalairmaroc.com/",
    "TU": "https://www.tunisair.com/",
    "TG": "https://www.thaiairways.com/",
    "GA": "https://www.garuda-indonesia.com/",
    "QF": "https://www.qantas.com/",
    "NZ": "https://www.airnewzealand.com/",
    "KE": "https://www.koreanair.com/",
    "OZ": "https://flyasiana.com/",
    "BR": "https://www.evaair.com/",
    "ET": "https://www.ethiopianairlines.com/",
    "KQ": "https://www.kenya-airways.com/",
    "SA": "https://www.flysaa.com/",
    "BI": "https://www.bruneiair.com/",
    "VN": "https://www.vietnamairlines.com/",
    "PR": "https://www.philippineairlines.com/",
    "SU": "https://www.aeroflot.com/",
    "9U": "https://www.airmoldova.md/",
    "FB": "https://www.air.bg/",
    "JU": "https://www.airserbia.com/",
    "BG": "https://www.biman-airlines.com/",
    "AI": "https://www.airindia.com/",
    "6E": "https://www.goindigo.in/",
    "UK": "https://www.airvistara.com/",
    "G9": "https://www.airarabia.com/",
    "J9": "https://www.jazeeraairways.com/",
    "OA": "https://en.olympicair.com/",
    "DT": "https://www.taag.com/",
    # Vettori vacanze/charter europei (homepage)
    "DE": "https://www.condor.com/",      # Condor
    "X3": "https://www.tuifly.com/",      # TUI fly Deutschland
    "BY": "https://www.tui.co.uk/flight/", # TUI Airways UK
    "TB": "https://www.tuifly.be/",       # TUI fly Belgium
    "OR": "https://www.tui.nl/",          # TUI fly Netherlands
    "EN": "https://www.airdolomiti.it/",  # Air Dolomiti
    "I2": "https://www.iberia.com/",      # Iberia Express
    "YW": "https://www.aireuropa.com/",   # Air Europa Express
    "UX": "https://www.aireuropa.com/",   # Air Europa
    "NT": "https://www.bintercanarias.com/",  # Binter Canarias
    "PS": "https://www.flyuia.com/",      # Ukraine International
    "B2": "https://www.belavia.by/",      # Belavia
    "BJ": "https://www.nouvelair.com/",   # Nouvelair Tunisia
    "VF": "https://www.flyvalan.com/",    # Valan
    "5O": "https://www.asl-airlines.fr/", # ASL Airlines France
    "TX": "https://www.airfranceaircaraibes.com/", # Air Caraibes
    "BF": "https://www.frenchbee.com/",   # French Bee
    "LY": "https://www.elal.com/",        # El Al
    "IZ": "https://www.arkia.com/",       # Arkia
    "FB": "https://www.air.bg/",          # Bulgaria Air
    "GQ": "https://www.skyexpress.gr/",   # Sky Express Greece
    "OB": "https://www.boa.bo/",          # Boliviana de Aviacion
    "AR": "https://www.aerolineas.com.ar/", # Aerolineas Argentinas
    "LA": "https://www.latam.com/",       # LATAM
    "JA": "https://www.flybosniaairlines.com/", # B&H Airlines
    "OG": "https://www.playflyplay.com/", # PLAY (Iceland)
}


def carrier_booking_url(carrier_code: str, origin: str, dest: str, date_iso: str) -> str:
    """Restituisce URL per il singolo segmento (deep link se conosciuto, altrimenti homepage)."""
    if carrier_code in AIRLINE_DEEP_LINKS:
        try:
            return AIRLINE_DEEP_LINKS[carrier_code](origin, dest, date_iso)
        except Exception:
            pass
    if carrier_code in AIRLINE_HOMEPAGES:
        return AIRLINE_HOMEPAGES[carrier_code]
    # Fallback: Google Flights (ha pagine pre-compilate per qualunque rotta+data)
    return f"https://www.google.com/travel/flights?q=Flights%20from%20{origin}%20to%20{dest}%20on%20{date_iso}"


def flight_booking_url(flight: Flight, airline: str, day: str, month_it: str, year: str) -> str:
    """URL del PRIMO segmento (usato per la rotta principale del volo)."""
    date_iso = f"{year}-{month_num(month_it)}-{day.zfill(2)}"
    segs = flight.segments or []
    if segs:
        s0 = segs[0]
        return carrier_booking_url(s0["carrier"], s0["origin"], s0["dest"], s0["date"])
    # Fallback per Aeroitalia/Ryanair "puri" senza segments
    o = flight.origin_airport or ""
    d = flight.dest_airport or ""
    if airline == "ryanair":
        return _ry_url(o, d, date_iso)
    if airline == "aeroitalia":
        return _ai_url(o, d, date_iso)
    return f"https://www.google.com/search?q={o}+{d}+{date_iso}"


async def send_long_message(chat, text: str, parse_mode: str = "Markdown", reply_markup=None, max_len: int = 4096):
    """Split and send a message that may exceed Telegram's 4096 char limit."""
    chunks = []
    while len(text) > max_len:
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    chunks.append(text)
    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        await chat.send_message(chunk, parse_mode=parse_mode, reply_markup=markup)


def format_leg(flights: List[Flight], orig: str, dest: str, dlabel: str,
               airline: str = "", day: str = "", month_it: str = "", year: str = "") -> list[str]:
    if not flights:
        return [f"❌ *Nessun volo* {orig} → {dest} il {dlabel}\n_(Sold Out o rotta non disponibile)_"]
    cheapest = min(flights, key=lambda f: float(f.price.replace("€", "").replace(",", ".")))
    lines = [f"✅ *{len(flights)} voli* {orig} → {dest} — {dlabel}\n_(Tocca la sigla del volo per aprire la pagina ufficiale della compagnia)_"]
    for f in flights:
        stops = getattr(f, "stops", None) or []
        o = getattr(f, "origin_airport", "") or orig
        d = getattr(f, "dest_airport", "") or dest
        if stops:
            route_text = f"{o} {f.departure} → {' → '.join(stops)} → {d} {f.arrival}"
            tail = f"_{len(stops)} scal{'i' if len(stops) > 1 else 'o'} · {f.duration}_"
        else:
            route_text = f"{o} {f.departure} → {d} {f.arrival}"
            tail = f"_diretto · {f.duration}_"

        # Costruisci link per ogni segmento (vettore reale di quella tratta)
        segs = getattr(f, "segments", None) or []
        if segs:
            seg_links = []
            for s in segs:
                url = carrier_booking_url(s["carrier"], s["origin"], s["dest"], s["date"])
                seg_links.append(f"[{s['carrier']}{s['code']}]({url})")
            flight_no_md = " + ".join(seg_links)
        else:
            # Aeroitalia/Ryanair "puri": un solo link sul numero volo
            if airline and day and month_it and year:
                url = flight_booking_url(f, airline, day, month_it, year)
                flight_no_md = f"[{f.flight_number}]({url})"
            else:
                flight_no_md = f"`{f.flight_number}`"

        lines.append(f"`{route_text}`\n  ✈ {flight_no_md}  *{f.price}*  {tail}")
    lines.append(f"💰 Miglior: *{cheapest.price}* ({cheapest.flight_number})")
    return lines


# ─── Conversation handlers ─────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton(f"✈️ {name}", callback_data=f"airline_{code}")]
        for code, name in AIRLINES.items()
    ]
    await update.message.reply_text(
        "✈️ *Benvenuto nel Flight Bot!*\n\nScegli la compagnia aerea:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return CHOOSE_AIRLINE


async def choose_airline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    code = query.data.replace("airline_", "")
    context.user_data["airline"] = code
    keyboard = [[
        InlineKeyboardButton("Sola andata ➡️", callback_data="trip_oneway"),
        InlineKeyboardButton("Andata e ritorno 🔄", callback_data="trip_roundtrip"),
    ]]
    await query.edit_message_text(
        f"Compagnia: *{AIRLINES[code]}*\n\nTipo di viaggio:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return CHOOSE_TRIP_TYPE


async def choose_trip_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    trip_type = query.data.replace("trip_", "")
    context.user_data["trip_type"] = trip_type
    label = "Sola andata ➡️" if trip_type == "oneway" else "Andata e ritorno 🔄"
    airline = context.user_data["airline"]
    keyboard = [[
        InlineKeyboardButton("⚡ Check istantaneo", callback_data="mode_instant"),
        InlineKeyboardButton("🔔 Notifica ogni ora", callback_data="mode_monitor"),
    ]]
    await query.edit_message_text(
        f"Compagnia: *{AIRLINES[airline]}*\n"
        f"Tipo: *{label}*\n\n"
        "Modalità ricerca:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return CHOOSE_MODE


async def choose_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    mode = query.data.replace("mode_", "")  # "instant" or "monitor"
    context.user_data["mode"] = mode
    airline = context.user_data["airline"]
    trip_type = context.user_data["trip_type"]
    label_trip = "Sola andata ➡️" if trip_type == "oneway" else "Andata e ritorno 🔄"
    label_mode = "⚡ Istantaneo" if mode == "instant" else "🔔 Ogni ora"
    hint = "es. BGY, MXP, BLQ, CIA…" if airline in ("ryanair", "kiwi") else "es. LIN, MXP, Linate…"
    await query.edit_message_text(
        f"Compagnia: *{AIRLINES[airline]}*\n"
        f"Tipo: *{label_trip}*\n"
        f"Modalità: *{label_mode}*\n\n"
        f"✈️ *Aeroporto di partenza?*\n_({hint})_",
        parse_mode="Markdown",
    )
    return ENTER_ORIGIN


async def enter_origin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    origin = update.message.text.strip()
    context.user_data["origin"] = origin
    airline = context.user_data.get("airline", "aeroitalia")
    hint = "es. PMO, CTA, BDS…" if airline in ("ryanair", "kiwi") else "es. CAG, FCO, Cagliari…"
    await update.message.reply_text(
        f"Partenza: *{origin.upper()}*\n\n"
        f"🛬 *Aeroporto di destinazione?*\n_({hint})_",
        parse_mode="Markdown",
    )
    return ENTER_DEST


async def enter_dest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    dest = update.message.text.strip()
    context.user_data["dest"] = dest
    await update.message.reply_text(
        f"Destinazione: *{dest.upper()}*\n\n"
        "📅 *Data di partenza?*\n"
        "• *Data precisa* → cerco i voli (es. `28`, `28/05`, `28/05/2026`)\n"
        "• *Mese* → mostro i giorni con voli (es. `luglio`, `lug`, `07/2026`)",
        parse_mode="Markdown",
    )
    return ENTER_DATE_GO


async def enter_date_go(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parsed = parse_month_or_date(update.message.text.strip())
    if parsed is None:
        await update.message.reply_text(
            "⚠️ Input non valido. Inserisci una *data* (es. 28, 28/05, 28/05/2026) "
            "o un *mese* (es. luglio, lug, 07/2026):",
            parse_mode="Markdown",
        )
        return ENTER_DATE_GO

    if parsed[0] == "month":
        _, month_it, year = parsed
        return await _show_month_availability(update, context, month_it, year, leg="go")

    _, day, month_it, year = parsed
    context.user_data["date_go"] = (day, month_it, year)

    if context.user_data.get("trip_type") == "roundtrip":
        await update.message.reply_text(
            f"Data andata: *{fmt_date(day, month_it, year)}*\n\n"
            "📅 *Data di ritorno?*\n_(data: 30, 30/05; oppure mese: luglio)_",
            parse_mode="Markdown",
        )
        return ENTER_DATE_RET

    return await _do_search(update, context)


async def enter_date_ret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parsed = parse_month_or_date(update.message.text.strip())
    if parsed is None:
        await update.message.reply_text(
            "⚠️ Input non valido. Inserisci una *data* (es. 30, 30/05, 30/05/2026) "
            "o un *mese* (es. luglio, lug, 07/2026):",
            parse_mode="Markdown",
        )
        return ENTER_DATE_RET

    if parsed[0] == "month":
        _, month_it, year = parsed
        return await _show_month_availability(update, context, month_it, year, leg="ret")

    _, day, month_it, year = parsed
    context.user_data["date_ret"] = (day, month_it, year)
    return await _do_search(update, context)


async def _show_month_availability(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    month_it: str, year: str, leg: str,
) -> int:
    """Mostra solo i giorni con voli (numero + giorno settimana), con bottoni cliccabili."""
    data = context.user_data
    airline = data.get("airline", "aeroitalia")
    origin_input = data["origin"]
    dest_input = data["dest"]

    if leg == "ret":
        from_input, to_input = dest_input, origin_input
    else:
        from_input, to_input = origin_input, dest_input

    wait_hint = {
        "ryanair": "~1 secondo",
        "kiwi": "~15 secondi",
        "aeroitalia": "~15 secondi",
    }.get(airline, "~15 secondi")
    await update.effective_chat.send_message(
        f"📅 Cerco giorni con voli in *{month_it.capitalize()} {year}* "
        f"({AIRLINES[airline]} {from_input.upper()} → {to_input.upper()})…\n_(attendi {wait_hint})_",
        parse_mode="Markdown",
    )

    try:
        if airline == "ryanair":
            origin_arg = airport_iata(from_input)
            dest_arg = airport_iata(to_input)
            days = await asyncio.to_thread(ryanair_available_days, origin_arg, dest_arg, month_it, year)
        elif airline == "kiwi":
            origin_arg = airport_iatas(from_input)
            dest_arg = airport_iatas(to_input)
            days = await asyncio.to_thread(kiwi_available_days, origin_arg, dest_arg, month_it, year)
        else:
            origin_arg = airport_search_term(from_input)
            dest_arg = airport_search_term(to_input)
            days = await asyncio.to_thread(aeroitalia_available_days, origin_arg, dest_arg, month_it, year)
    except Exception as e:
        await update.effective_chat.send_message(f"❌ Errore: `{e}`", parse_mode="Markdown")
        return ConversationHandler.END

    text = format_available_days(days, from_input.upper(), to_input.upper(), month_it, year)

    # Build day buttons (4 per row)
    button_rows = []
    row = []
    for day, wd in days:
        row.append(InlineKeyboardButton(
            f"{wd} {day}",
            callback_data=f"pickday_{day}_{month_it}_{year}_{leg}",
        ))
        if len(row) == 4:
            button_rows.append(row)
            row = []
    if row:
        button_rows.append(row)

    round_trip = data.get("trip_type") == "roundtrip"
    if not button_rows:
        # No days available
        button_rows.append([InlineKeyboardButton("🔄 Nuova ricerca", callback_data="new_search")])
        hint = ""
    else:
        hint = "\n\n_Tocca un giorno per cercare i voli._"

    await update.effective_chat.send_message(
        text + hint,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(button_rows),
    )

    # Round-trip: dopo aver mostrato l'andata, chiedi anche il ritorno
    if round_trip and leg == "go":
        await update.effective_chat.send_message(
            "📅 *Data/mese di ritorno?*\n"
            "_(es. `15`, `15/08`, oppure `agosto`)_",
            parse_mode="Markdown",
        )
        return ENTER_DATE_RET

    # Resta nello stato corrente per accettare button click o nuovo input
    return ENTER_DATE_RET if leg == "ret" else ENTER_DATE_GO


async def pickday_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gestisce il click su un bottone giorno (pickday_DD_MMM_YYYY_LEG)."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 5:
        return ConversationHandler.END
    day, month_it, year, leg = parts[1], parts[2], parts[3], parts[4]
    context.user_data[f"date_{leg}"] = (day, month_it, year)
    await query.message.reply_text(
        f"✅ {'Ritorno' if leg == 'ret' else 'Andata'}: *{fmt_date(day, month_it, year)}*",
        parse_mode="Markdown",
    )

    round_trip = context.user_data.get("trip_type") == "roundtrip"
    has_go = "date_go" in context.user_data
    has_ret = "date_ret" in context.user_data

    if not round_trip or (has_go and has_ret):
        return await _do_search(update, context)

    # Round-trip ma manca un leg
    if not has_go:
        await query.message.reply_text(
            "📅 *Data/mese di andata?*",
            parse_mode="Markdown",
        )
        return ENTER_DATE_GO
    else:
        await query.message.reply_text(
            "📅 *Data/mese di ritorno?*",
            parse_mode="Markdown",
        )
        return ENTER_DATE_RET


async def _do_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = context.user_data
    origin_input = data["origin"]
    dest_input = data["dest"]
    day_go, month_go, year_go = data["date_go"]
    round_trip = data.get("trip_type") == "roundtrip"

    airline = data.get("airline", "aeroitalia")
    if airline == "ryanair":
        origin_arg = airport_iata(origin_input)
        dest_arg = airport_iata(dest_input)
        scraper = scrape_flights_ryanair
        wait_hint_single = "~30 secondi"
        wait_hint_round = "~1 minuto"
    elif airline == "kiwi":
        origin_arg = airport_iatas(origin_input)  # lista di IATA per Kiwi
        dest_arg = airport_iatas(dest_input)
        scraper = scrape_flights_kiwi
        wait_hint_single = "~3 secondi"
        wait_hint_round = "~6 secondi"
    else:
        origin_arg = airport_search_term(origin_input)
        dest_arg = airport_search_term(dest_input)
        scraper = scrape_flights
        wait_hint_single = "~2 minuti"
        wait_hint_round = "~4 minuti"

    dlabel_go = fmt_date(day_go, month_go, year_go)

    if round_trip:
        day_ret, month_ret, year_ret = data["date_ret"]
        dlabel_ret = fmt_date(day_ret, month_ret, year_ret)
        status = (
            f"🔍 Cerco ({AIRLINES[airline]}):\n"
            f"*{origin_input.upper()} → {dest_input.upper()}* il *{dlabel_go}*\n"
            f"*{dest_input.upper()} → {origin_input.upper()}* il *{dlabel_ret}*\n"
            f"_(attendi {wait_hint_round})_"
        )
    else:
        status = (
            f"🔍 Cerco ({AIRLINES[airline]}) *{origin_input.upper()} → {dest_input.upper()}* il *{dlabel_go}*…\n"
            f"_(attendi {wait_hint_single})_"
        )

    await update.effective_chat.send_message(status, parse_mode="Markdown")

    try:
        flights_go = await asyncio.to_thread(scraper, origin_arg, dest_arg, day_go, month_go, year_go)
    except Exception as e:
        err_msg = str(e)[:300]
        await update.effective_chat.send_message(f"❌ Errore ricerca andata:\n`{err_msg}`", parse_mode="Markdown")
        return ConversationHandler.END

    lines = format_leg(flights_go, origin_input.upper(), dest_input.upper(), dlabel_go,
                       airline=airline, day=day_go, month_it=month_go, year=year_go)

    flights_ret = None
    if round_trip:
        lines.append("")
        try:
            flights_ret = await asyncio.to_thread(scraper, dest_arg, origin_arg, day_ret, month_ret, year_ret)
        except Exception as e:
            lines.append(f"❌ Errore ricerca ritorno:\n`{e}`")
            await update.effective_chat.send_message("\n".join(lines), parse_mode="Markdown")
            return ConversationHandler.END
        lines += format_leg(flights_ret, dest_input.upper(), origin_input.upper(), dlabel_ret,
                            airline=airline, day=day_ret, month_it=month_ret, year=year_ret)

        if flights_go and flights_ret:
            best_go = min(flights_go, key=lambda f: float(f.price.replace("€", "").replace(",", ".")))
            best_ret = min(flights_ret, key=lambda f: float(f.price.replace("€", "").replace(",", ".")))
            total = (
                float(best_go.price.replace("€", "").replace(",", ".")) +
                float(best_ret.price.replace("€", "").replace(",", "."))
            )
            lines.append(f"\n🧳 *Totale A/R minimo: {total:.2f}€*")

    # Giorni vicini con voli (Ryanair via API, Kiwi via query mensili)
    prev_btns_go = next_btns_go = None
    prev_btns_ret = next_btns_ret = None
    nearest_fn = None
    if airline == "ryanair":
        nearest_fn = ryanair_nearest_days
    elif airline == "kiwi":
        nearest_fn = kiwi_nearest_days

    if nearest_fn:
        prev_go, next_go = await asyncio.to_thread(
            nearest_fn, origin_arg, dest_arg, month_go, year_go, day_go
        )
        if prev_go or next_go:
            lines.append(f"\n🔍 *Giorni vicini con voli — andata:*")
            if prev_go:
                lines.append(f"  ⬅ `{prev_go[1]} {prev_go[0]} {month_go}`")
            if next_go:
                lines.append(f"  ➡ `{next_go[1]} {next_go[0]} {month_go}`")
            prev_btns_go = prev_go
            next_btns_go = next_go
        if round_trip:
            prev_ret, next_ret = await asyncio.to_thread(
                nearest_fn, dest_arg, origin_arg, month_ret, year_ret, day_ret
            )
            if prev_ret or next_ret:
                lines.append(f"\n🔍 *Giorni vicini con voli — ritorno:*")
                if prev_ret:
                    lines.append(f"  ⬅ `{prev_ret[1]} {prev_ret[0]} {month_ret}`")
                if next_ret:
                    lines.append(f"  ➡ `{next_ret[1]} {next_ret[0]} {month_ret}`")
                prev_btns_ret = prev_ret
                next_btns_ret = next_ret

    mode = data.get("mode", "instant")

    # Build keyboard
    keyboard_rows = []
    nav_row_go = []
    if prev_btns_go:
        nav_row_go.append(InlineKeyboardButton(
            f"⬅ Andata {prev_btns_go[0]}/{month_num(month_go)}",
            callback_data=f"pickday_{prev_btns_go[0]}_{month_go}_{year_go}_go",
        ))
    if next_btns_go:
        nav_row_go.append(InlineKeyboardButton(
            f"➡ Andata {next_btns_go[0]}/{month_num(month_go)}",
            callback_data=f"pickday_{next_btns_go[0]}_{month_go}_{year_go}_go",
        ))
    if nav_row_go:
        keyboard_rows.append(nav_row_go)
    if round_trip:
        nav_row_ret = []
        if prev_btns_ret:
            nav_row_ret.append(InlineKeyboardButton(
                f"⬅ Ritorno {prev_btns_ret[0]}/{month_num(month_ret)}",
                callback_data=f"pickday_{prev_btns_ret[0]}_{month_ret}_{year_ret}_ret",
            ))
        if next_btns_ret:
            nav_row_ret.append(InlineKeyboardButton(
                f"➡ Ritorno {next_btns_ret[0]}/{month_num(month_ret)}",
                callback_data=f"pickday_{next_btns_ret[0]}_{month_ret}_{year_ret}_ret",
            ))
        if nav_row_ret:
            keyboard_rows.append(nav_row_ret)

    if mode == "monitor":
        key = register_monitor(
            context=context,
            user_id=update.effective_user.id,
            chat_id=update.effective_chat.id,
            airline=airline,
            trip_type="roundtrip" if round_trip else "oneway",
            origin_input=origin_input,
            dest_input=dest_input,
            date_go=list(data["date_go"]),
            date_ret=list(data["date_ret"]) if round_trip else None,
            flights_go=flights_go,
            flights_ret=flights_ret if round_trip else None,
        )
        lines.append(f"\n🔔 *Monitoraggio attivo* — ti notifico ogni ora se cambia qualcosa")
        keyboard_rows.append([
            InlineKeyboardButton("⏹ Ferma questo monitor", callback_data=f"stopmon_{key}"),
            InlineKeyboardButton("🔄 Nuova ricerca", callback_data="new_search"),
        ])
    else:
        keyboard_rows.append([InlineKeyboardButton("🔄 Nuova ricerca", callback_data="new_search")])

    await send_long_message(
        update.effective_chat,
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard_rows),
    )
    return ConversationHandler.END


# ─── Monitor registration & scheduled check ───────────────────────────────────

def flights_to_state(flights: Optional[List[Flight]]) -> dict:
    """Serialize flights to {flight_number: price} for diff comparison."""
    if not flights:
        return {}
    return {f.flight_number: f.price for f in flights}


def register_monitor(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    chat_id: int,
    airline: str,
    trip_type: str,
    origin_input: str,
    dest_input: str,
    date_go: list,
    date_ret: Optional[list],
    flights_go: List[Flight],
    flights_ret: Optional[List[Flight]],
) -> str:
    key = monitor_key(user_id, airline, origin_input.upper(), dest_input.upper(), date_go, date_ret)
    monitors = load_monitors()
    monitors[key] = {
        "user_id": user_id,
        "chat_id": chat_id,
        "airline": airline,
        "trip_type": trip_type,
        "origin_input": origin_input,
        "dest_input": dest_input,
        "date_go": date_go,
        "date_ret": date_ret,
        "last_go": flights_to_state(flights_go),
        "last_ret": flights_to_state(flights_ret),
    }
    save_monitors(monitors)
    # Schedule the hourly job
    context.job_queue.run_repeating(
        scheduled_check,
        interval=MONITOR_INTERVAL,
        first=MONITOR_INTERVAL,
        chat_id=chat_id,
        user_id=user_id,
        name=key,
        data={"key": key},
    )
    return key


def diff_flights(prev: dict, curr: dict) -> tuple[list, list, list]:
    """Return (new_flights, price_changes, removed_flights)."""
    prev_keys = set(prev.keys())
    curr_keys = set(curr.keys())
    new = [(fn, curr[fn]) for fn in curr_keys - prev_keys]
    removed = [(fn, prev[fn]) for fn in prev_keys - curr_keys]
    changed = [
        (fn, prev[fn], curr[fn])
        for fn in prev_keys & curr_keys
        if prev[fn] != curr[fn]
    ]
    return new, changed, removed


async def scheduled_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    key = job.data["key"]
    monitors = load_monitors()
    mon = monitors.get(key)
    if not mon:
        # Monitor was removed — cancel this job
        job.schedule_removal()
        return

    airline = mon["airline"]
    if airline == "ryanair":
        origin_arg = airport_iata(mon["origin_input"])
        dest_arg = airport_iata(mon["dest_input"])
        scraper = scrape_flights_ryanair
    elif airline == "kiwi":
        origin_arg = airport_iatas(mon["origin_input"])
        dest_arg = airport_iatas(mon["dest_input"])
        scraper = scrape_flights_kiwi
    else:
        origin_arg = airport_search_term(mon["origin_input"])
        dest_arg = airport_search_term(mon["dest_input"])
        scraper = scrape_flights

    date_go = mon["date_go"]
    date_ret = mon["date_ret"]
    round_trip = date_ret is not None

    try:
        flights_go = await asyncio.to_thread(scraper, origin_arg, dest_arg, date_go[0], date_go[1], date_go[2])
    except Exception as e:
        logging.error(f"Monitor {key} scrape error (andata): {e}")
        return

    flights_ret = None
    if round_trip:
        try:
            flights_ret = await asyncio.to_thread(scraper, dest_arg, origin_arg, date_ret[0], date_ret[1], date_ret[2])
        except Exception as e:
            logging.error(f"Monitor {key} scrape error (ritorno): {e}")
            return

    # Compute diff vs last state
    curr_go = flights_to_state(flights_go)
    curr_ret = flights_to_state(flights_ret)
    new_go, chg_go, rem_go = diff_flights(mon["last_go"], curr_go)
    new_ret, chg_ret, rem_ret = (
        diff_flights(mon["last_ret"] or {}, curr_ret) if round_trip else ([], [], [])
    )

    has_changes = any([new_go, chg_go, rem_go, new_ret, chg_ret, rem_ret])
    if not has_changes:
        return  # silent — no notification when nothing changed

    # Build notification
    dlabel_go = fmt_date(date_go[0], date_go[1], date_go[2])
    lines = [f"🔔 *Aggiornamento {AIRLINES[airline]}* — {mon['origin_input'].upper()} ↔ {mon['dest_input'].upper()}"]

    def fmt_diff(leg: str, dlabel: str, new, chg, rem):
        out = [f"\n📅 *{leg}* — {dlabel}"]
        if new:
            out.append("✨ *Nuovi voli:*")
            for fn, pr in new:
                out.append(f"  + `{fn}`  {pr}")
        if chg:
            out.append("💱 *Prezzi cambiati:*")
            for fn, op, np in chg:
                arrow = "📉" if _price_val(np) < _price_val(op) else "📈"
                out.append(f"  {arrow} `{fn}`  {op} → *{np}*")
        if rem:
            out.append("❌ *Voli rimossi/sold out:*")
            for fn, pr in rem:
                out.append(f"  - `{fn}`  era {pr}")
        return out

    lines += fmt_diff("Andata", dlabel_go, new_go, chg_go, rem_go)
    if round_trip:
        dlabel_ret = fmt_date(date_ret[0], date_ret[1], date_ret[2])
        lines += fmt_diff("Ritorno", dlabel_ret, new_ret, chg_ret, rem_ret)

    keyboard = [[InlineKeyboardButton("⏹ Ferma questo monitor", callback_data=f"stopmon_{key}")]]
    try:
        await context.bot.send_message(
            chat_id=job.chat_id,
            text="\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logging.error(f"Monitor {key} send error: {e}")
        return

    # Update saved state
    mon["last_go"] = curr_go
    mon["last_ret"] = curr_ret
    monitors[key] = mon
    save_monitors(monitors)


def _price_val(price: str) -> float:
    try:
        return float(price.replace("€", "").replace(",", ".").strip())
    except Exception:
        return 0.0


async def new_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_reply_markup(reply_markup=None)
    keyboard = [
        [InlineKeyboardButton(f"✈️ {name}", callback_data=f"airline_{code}")]
        for code, name in AIRLINES.items()
    ]
    await query.message.reply_text(
        "✈️ Scegli la compagnia aerea:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return CHOOSE_AIRLINE


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Ricerca annullata. Usa /start per ricominciare.")
    return ConversationHandler.END


# ─── Monitor management commands ──────────────────────────────────────────────

async def list_monitors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    monitors = load_monitors()
    mine = {k: m for k, m in monitors.items() if m.get("user_id") == user_id}
    if not mine:
        await update.message.reply_text(
            "Non hai monitor attivi. Usa /start e scegli *🔔 Notifica ogni ora* per crearne uno.",
            parse_mode="Markdown",
        )
        return

    lines = [f"🔔 *Monitor attivi ({len(mine)})*"]
    for key, m in mine.items():
        dlabel = fmt_date(*m["date_go"])
        suffix = f" / ritorno {fmt_date(*m['date_ret'])}" if m.get("date_ret") else ""
        lines.append(
            f"\n• {AIRLINES.get(m['airline'], m['airline'])}: "
            f"*{m['origin_input'].upper()} → {m['dest_input'].upper()}* il {dlabel}{suffix}"
        )

    keyboard = [
        [InlineKeyboardButton(
            f"⏹ {m['origin_input'].upper()}→{m['dest_input'].upper()} {fmt_date(*m['date_go'])}",
            callback_data=f"stopmon_{key}",
        )]
        for key, m in mine.items()
    ]
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def stop_monitor_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    key = query.data.replace("stopmon_", "")
    monitors = load_monitors()
    if key not in monitors:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Monitor già rimosso.")
        return
    if monitors[key].get("user_id") != update.effective_user.id:
        await query.message.reply_text("⚠️ Non puoi fermare un monitor non tuo.")
        return

    del monitors[key]
    save_monitors(monitors)

    for job in context.job_queue.get_jobs_by_name(key):
        job.schedule_removal()

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("⏹ Monitor fermato.")


# ─── Startup: restore monitors ────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.exception("Exception in handler:", exc_info=context.error)
    try:
        chat_id = None
        if isinstance(update, Update):
            chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Errore interno: `{context.error}`",
                parse_mode="Markdown",
            )
    except Exception:
        pass


async def restore_monitors(app: Application) -> None:
    monitors = load_monitors()
    for key, m in monitors.items():
        app.job_queue.run_repeating(
            scheduled_check,
            interval=MONITOR_INTERVAL,
            first=MONITOR_INTERVAL,
            chat_id=m["chat_id"],
            user_id=m["user_id"],
            name=key,
            data={"key": key},
        )
    if monitors:
        logging.info(f"Restored {len(monitors)} monitor(s)")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(restore_monitors)
        .build()
    )

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(new_search_callback, pattern="^new_search$"),
        ],
        states={
            CHOOSE_AIRLINE:   [CallbackQueryHandler(choose_airline, pattern="^airline_")],
            CHOOSE_TRIP_TYPE: [CallbackQueryHandler(choose_trip_type, pattern="^trip_")],
            CHOOSE_MODE:      [CallbackQueryHandler(choose_mode, pattern="^mode_")],
            ENTER_ORIGIN:     [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_origin)],
            ENTER_DEST:       [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_dest)],
            ENTER_DATE_GO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_date_go),
                CallbackQueryHandler(pickday_callback, pattern="^pickday_"),
            ],
            ENTER_DATE_RET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_date_ret),
                CallbackQueryHandler(pickday_callback, pattern="^pickday_"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("monitors", list_monitors))
    app.add_handler(CallbackQueryHandler(stop_monitor_callback, pattern="^stopmon_"))
    # pickday globale: gestisce i bottoni prev/next nei risultati DOPO che la conv è terminata
    app.add_handler(CallbackQueryHandler(pickday_callback, pattern="^pickday_"))
    app.add_error_handler(error_handler)

    print("🤖 Bot avviato — in ascolto su Telegram…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
