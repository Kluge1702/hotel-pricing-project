"""
scraper.py
----------
Scraper Booking.com dla Gdyni obsługujący pokoje 1-osobowe (1 dorosły) oraz 2-osobowe (2 dorosłych).
Wykorzystuje Infinite Scroll, wykrywa benchmark HOLA Gdynia i filtruje substytuty.
"""

import os
import sys
import subprocess
import statistics
import re
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any

def _ensure_playwright_installed():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        pass

_ensure_playwright_installed()
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def _get_fallback_prices(adults: int = 2, reason: str = "") -> Dict[str, Any]:
    """Estymacja zapasowa z podziałem na pokoje 1-osobowe i 2-osobowe."""
    if adults == 1:
        fallback_data = [
            {"hotel": "HOLA GDYNIA", "price": 365.0, "type": "Hotel / Obiekt"},
            {"hotel": "Courtyard by Marriott Gdynia Waterfront", "price": 310.0, "type": "Hotel / Obiekt"},
            {"hotel": "Mercure Gdynia Centrum", "price": 349.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Nadmorski", "price": 330.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotton Hotel", "price": 279.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Dom Marynarza", "price": 235.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Antares Gdynia", "price": 320.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Gdynia Boutique", "price": 330.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Willa Lubicz", "price": 319.0, "type": "Hotel / Obiekt"},
            {"hotel": "Willa Pieńkowskich", "price": 270.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Kuracyjny Spa & Wellness", "price": 265.0, "type": "Hotel / Obiekt"},
            {"hotel": "SQUARE APARTMENTS GDYNIA", "price": 310.0, "type": "Apartament 1-os."},
            {"hotel": "7th Floor Rooms Gdynia", "price": 365.0, "type": "Apartament 1-os."},
            {"hotel": "Kamienica Morska Gdynia", "price": 260.0, "type": "Apartament 1-os."},
            {"hotel": "Studio Świętojańska Centrum", "price": 220.0, "type": "Apartament 1-os."}
        ]
        hola_p = 365.0
    else:
        fallback_data = [
            {"hotel": "HOLA GDYNIA", "price": 421.0, "type": "Hotel / Obiekt"},
            {"hotel": "Courtyard by Marriott Gdynia Waterfront", "price": 344.0, "type": "Hotel / Obiekt"},
            {"hotel": "Mercure Gdynia Centrum", "price": 397.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Nadmorski", "price": 380.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotton Hotel", "price": 318.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Dom Marynarza", "price": 271.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Antares Gdynia", "price": 370.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Gdynia Boutique", "price": 381.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Willa Lubicz", "price": 365.0, "type": "Hotel / Obiekt"},
            {"hotel": "Willa Pieńkowskich", "price": 314.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Kuracyjny Spa & Wellness", "price": 304.0, "type": "Hotel / Obiekt"},
            {"hotel": "My Story Gdynia Hotel", "price": 559.0, "type": "Hotel / Obiekt"},
            {"hotel": "SQUARE APARTMENTS GDYNIA", "price": 357.0, "type": "Apartament 2-os."},
            {"hotel": "7th Floor Rooms & Apartments", "price": 424.0, "type": "Apartament 2-os."},
            {"hotel": "Kamienica Morska Gdynia", "price": 302.0, "type": "Apartament 2-os."},
            {"hotel": "Villa Orla Gdynia", "price": 349.0, "type": "Apartament 2-os."},
            {"hotel": "Apartamenty Efekt 72", "price": 410.0, "type": "Apartament 2-os."},
            {"hotel": "Gdynia Centrum Studio", "price": 340.0, "type": "Apartament 2-os."}
        ]
        hola_p = 421.0

    prices = [item["price"] for item in fallback_data]
    hotel_prices = [item["price"] for item in fallback_data if item["type"] == "Hotel / Obiekt"]
    apt_prices = [item["price"] for item in fallback_data if "Apartament" in item["type"]]

    return {
        "prices": prices,
        "details": fallback_data,
        "hola_price": hola_p,
        "adults": adults,
        "hotel_avg": round(statistics.mean(hotel_prices), 2),
        "apt_avg": round(statistics.mean(apt_prices), 2),
        "hotel_count": len(hotel_prices),
        "apt_count": len(apt_prices),
        "przejrzano_obiektow": len(fallback_data),
        "pobrano_cen": len(prices),
        "min_price": float(min(prices)),
        "avg_price": float(round(statistics.mean(prices), 2)),
        "median_price": float(round(statistics.median(prices), 2)),
        "max_price": float(max(prices)),
        "source": "fallback_estimate",
        "message": f"Użyto estymacji rynkowej ({adults} os.). {reason}".strip()
    }


def _extract_price(card) -> float:
    """Ekstraktor kwoty odporny na kolejność waluty (PLN 344, 344 zł, zł 344, 344 PLN)."""
    price_node = card.query_selector('[data-testid="price-and-discounted-price"]')
    if price_node:
        txt = price_node.inner_text().replace("\xa0", " ").strip()
        nums = re.findall(r'\b\d[\d\s]{1,5}\b', txt)
        if nums:
            clean = re.sub(r"[^\d]", "", nums[-1])
            if clean:
                val = float(clean)
                if 90.0 <= val <= 2500.0:
                    return val

    for sel in ['[data-testid="price"]', '.b87c397a13', '[data-testid="availability-rate-information"]']:
        node = card.query_selector(sel)
        if node:
            txt = node.inner_text().replace("\xa0", " ").strip()
            match = re.search(r'(?:PLN|zł)\s*(\d[\d\s]{1,5})|(\d[\d\s]{1,5})\s*(?:PLN|zł)', txt, re.IGNORECASE)
            if match:
                raw_num = match.group(1) or match.group(2)
                clean = re.sub(r"[^\d]", "", raw_num)
                if clean:
                    val = float(clean)
                    if 90.0 <= val <= 2500.0:
                        return val

    card_text = card.inner_text().replace("\xa0", " ")
    matches = re.findall(r'(?:PLN|zł)\s*(\d[\d\s]{1,5})|(\d[\d\s]{1,5})\s*(?:PLN|zł)', card_text, re.IGNORECASE)
    if matches:
        last_match = matches[-1]
        raw_num = last_match[0] or last_match[1]
        clean = re.sub(r"[^\d]", "", raw_num)
        if clean:
            val = float(clean)
            if 90.0 <= val <= 2500.0:
                return val

    return 0.0


def _classify_property_type(name: str, adults: int = 2) -> str:
    """Precyzyjnie rozróżnia hotele od apartamentów dla wybranej liczby gości."""
    name_lower = name.lower()
    hotel_indicators = [
        "hotel", "hola", "marriott", "mercure", "courtyard", "radisson",
        "accor", "willa", "boutique", "dworek", "spa", "resort", "batory",
        "blick", "hotton", "antares", "marynarz", "pensjonat", "inn", "relais"
    ]
    if any(h in name_lower for h in hotel_indicators):
        return "Hotel / Obiekt"
    return f"Apartament {adults}-os."


def fetch_gdynia_competitor_prices(
    checkin_date: str = None,
    checkout_date: str = None,
    adults: int = 2
) -> Dict[str, Any]:
    """
    Pobiera ceny z Booking.com dla Gdyni dla 1 lub 2 osób.
    """
    adults = 1 if int(adults) == 1 else 2

    if not checkin_date:
        today = datetime.today()
        checkin_dt = today + timedelta(days=1)
        checkout_dt = checkin_dt + timedelta(days=1)
        checkin_date = checkin_dt.strftime("%Y-%m-%d")
        checkout_date = checkout_dt.strftime("%Y-%m-%d")

    details_list: List[Dict[str, Any]] = []
    found_hola_price = None

    strict_exclusions = [
        "2 sypialn", "3 sypialn", "4 sypialn", "dwie sypialnie", "trzy sypialnie",
        "dla 4 osób", "dla 5 osób", "dla 6 osób", "dla 8 osób",
        "wspólna łazienka", "kwatera pracownicza"
    ]

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--window-size=1920,1080",
                    "--lang=pl-PL,pl"
                ]
            )

            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="pl-PL",
                timezone_id="Europe/Warsaw"
            )

            context.add_cookies([
                {"name": "selected_currency", "value": "PLN", "domain": ".booking.com", "path": "/"},
                {"name": "b_lang", "value": "pl", "domain": ".booking.com", "path": "/"}
            ])

            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'languages', { get: () => ['pl-PL', 'pl', 'en-US', 'en'] });
            """)

            page = context.new_page()

            url = (
                f"https://www.booking.com/searchresults.pl.html?"
                f"ss=Gdynia&dest_id=-501414&dest_type=city"
                f"&checkin={checkin_date}&checkout={checkout_date}"
                f"&group_adults={adults}&no_rooms=1&group_children=0"
                f"&selected_currency=PLN"
            )

            try:
                page.goto(url, timeout=35000, wait_until="domcontentloaded")
            except PlaywrightTimeoutError:
                pass

            time.sleep(2.5)

            # Zamknięcie ciasteczek
            for btn_sel in [
                'button#onetrust-accept-btn-handler',
                'button[aria-label="Odwrzuć"]',
                'button[aria-label="Odrzuć"]',
                'button[aria-label="Zamknij"]'
            ]:
                try:
                    b = page.query_selector(btn_sel)
                    if b and b.is_visible():
                        b.click()
                        time.sleep(0.3)
                except Exception:
                    pass

            # Infinite Scroll – doładowanie kolejnych ofert
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)

            page_height = page.evaluate("document.body.scrollHeight")
            steps = 5
            for s in range(1, steps + 1):
                page.evaluate(f"window.scrollTo(0, {int(page_height * (s / steps))});")
                time.sleep(0.3)

            cards = page.query_selector_all('[data-testid="property-card"]')
            total_cards_seen = len(cards)
            print(f"[DEBUG SCRAPER] Znaleziono kart ({adults} os.): {total_cards_seen}", flush=True)

            for card in cards:
                title_elem = card.query_selector('[data-testid="title"]')
                if not title_elem:
                    continue
                name = title_elem.inner_text().strip()
                card_full_text = card.inner_text().lower()

                if any(bad in card_full_text for bad in strict_exclusions):
                    continue

                price_val = _extract_price(card)
                if 90.0 <= price_val <= 1800.0:
                    prop_type = _classify_property_type(name, adults=adults)
                    details_list.append({
                        "hotel": name,
                        "price": price_val,
                        "type": prop_type
                    })

                    if "hola" in name.lower() and found_hola_price is None:
                        found_hola_price = price_val

            browser.close()

        # Deduplikacja
        seen = set()
        unique_details = []
        for item in details_list:
            key = (item["hotel"], item["price"])
            if key not in seen:
                seen.add(key)
                unique_details.append(item)

        unique_prices = sorted([item["price"] for item in unique_details])
        print(f"[DEBUG SCRAPER] Zakwalifikowano ofert ({adults} os.): {len(unique_details)}.", flush=True)

        if len(unique_prices) < 5:
            return _get_fallback_prices(adults=adults, reason=f"Zbyt mała liczba ofert ({len(unique_prices)}).")

        hotel_prices = [item["price"] for item in unique_details if item["type"] == "Hotel / Obiekt"]
        apt_prices = [item["price"] for item in unique_details if "Apartament" in item["type"]]

        hotel_avg = round(statistics.mean(hotel_prices), 2) if hotel_prices else round(statistics.mean(unique_prices), 2)
        apt_avg = round(statistics.mean(apt_prices), 2) if apt_prices else round(statistics.mean(unique_prices), 2)

        return {
            "prices": unique_prices,
            "details": unique_details,
            "hola_price": found_hola_price,
            "adults": adults,
            "hotel_avg": hotel_avg,
            "apt_avg": apt_avg,
            "hotel_count": len(hotel_prices),
            "apt_count": len(apt_prices),
            "przejrzano_obiektow": total_cards_seen,
            "pobrano_cen": len(unique_details),
            "min_price": float(min(unique_prices)),
            "avg_price": float(round(statistics.mean(unique_prices), 2)),
            "median_price": float(round(statistics.median(unique_prices), 2)),
            "max_price": float(max(unique_prices)),
            "source": "booking_live",
            "message": f"Pobrano {len(unique_details)} ofert na żywo dla {adults} os. (Hotele: {len(hotel_prices)}, Apartamenty: {len(apt_prices)})."
        }

    except Exception as e:
        return _get_fallback_prices(adults=adults, reason=f"Błąd: {str(e)}")


if __name__ == "__main__":
    print("=" * 65)
    print("TEST SCRAPERA DLA 1 OSOBY ORAZ 2 OSÓB")
    print("=" * 65)
    for guests in [1, 2]:
        print(f"\n--- SKANOWANIE DLA {guests} GOŚCIA/GOŚCI ---")
        res = fetch_gdynia_competitor_prices(adults=guests)
        print("Status:", res["message"])
        print("HOLA Gdynia:", res.get("hola_price"))
        print(f"Średnia Hoteli: {res.get('hotel_avg')} PLN | Średnia Apartamentów: {res.get('apt_avg')} PLN")
        if res.get("details"):
            print("Przykładowe 3 obiekty:")
            for h in res["details"][:3]:
                print(f"  * [{h['type']}] {h['hotel']} : {h['price']:.0f} PLN")
