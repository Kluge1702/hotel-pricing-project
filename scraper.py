"""
scraper.py
----------
Scraper Booking.com dla Gdyni (obsługa 1 os. i 2 os.) z wymuszeniem cen brutto
(z podatkami i opłatami), automatycznym doliczaniem ukrytych podatków Geo-IP
oraz wykluczeniem własnego obiektu (Baltic Hotel).
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
            {"hotel": "HOLA GDYNIA", "price": 365.0, "base_price": 365.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Courtyard by Marriott Gdynia Waterfront", "price": 345.0, "base_price": 345.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Mercure Gdynia Centrum", "price": 360.0, "base_price": 360.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Nadmorski", "price": 330.0, "base_price": 330.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotton Hotel", "price": 279.0, "base_price": 279.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Dom Marynarza", "price": 255.0, "base_price": 255.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Antares Gdynia", "price": 320.0, "base_price": 320.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Willa Lubicz", "price": 319.0, "base_price": 319.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "SQUARE APARTMENTS GDYNIA", "price": 310.0, "base_price": 310.0, "taxes_added": 0.0, "type": "Apartament 1-os."},
            {"hotel": "Kamienica Morska Gdynia", "price": 260.0, "base_price": 260.0, "taxes_added": 0.0, "type": "Apartament 1-os."}
        ]
        hola_p = 365.0
    else:
        fallback_data = [
            {"hotel": "HOLA GDYNIA", "price": 421.0, "base_price": 421.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Courtyard by Marriott Gdynia Waterfront", "price": 382.0, "base_price": 382.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Mercure Gdynia Centrum", "price": 397.0, "base_price": 397.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Nadmorski", "price": 380.0, "base_price": 380.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Różany Gaj - Destigo Hotels", "price": 359.0, "base_price": 359.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotton Hotel", "price": 318.0, "base_price": 318.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Dom Marynarza", "price": 286.0, "base_price": 286.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Antares Gdynia", "price": 370.0, "base_price": 370.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "Hotel Willa Lubicz", "price": 365.0, "base_price": 365.0, "taxes_added": 0.0, "type": "Hotel / Obiekt"},
            {"hotel": "SQUARE APARTMENTS GDYNIA", "price": 357.0, "base_price": 357.0, "taxes_added": 0.0, "type": "Apartament 2-os."},
            {"hotel": "44 Apart", "price": 283.0, "base_price": 283.0, "taxes_added": 0.0, "type": "Apartament 2-os."},
            {"hotel": "Kamienica Morska Gdynia", "price": 302.0, "base_price": 302.0, "taxes_added": 0.0, "type": "Apartament 2-os."}
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


def _parse_amount(text: str) -> float:
    """Wyciąga ostatnią kwotę numeryczną z tekstu (odporne na przekreślone stare ceny)."""
    if not text:
        return 0.0
    clean_txt = text.replace("\xa0", " ").strip()
    # Szukamy kwot przy walucie (np. '340 zł 283 zł' -> bierze ostatnią aktualną '283')
    matches = re.findall(r'(?:PLN|zł)\s*(\d[\d\s]{0,5})|(\d[\d\s]{0,5})\s*(?:PLN|zł)', clean_txt, re.IGNORECASE)
    if matches:
        last = matches[-1]
        raw = last[0] or last[1]
        digits = re.sub(r"[^\d]", "", raw)
        if digits:
            return float(digits)

    nums = re.findall(r'\b\d[\d\s]{0,5}\b', clean_txt)
    if nums:
        digits = re.sub(r"[^\d]", "", nums[-1])
        if digits:
            return float(digits)
    return 0.0


def _extract_taxes(card) -> float:
    """
    Sprawdza, czy pod ceną znajduje się dopisek o dodatkowych podatkach/opłatach
    (np. '+ 35 zł podatków i opłat' przy IP spoza Polski). Jeśli jest 'Zawiera opłaty i podatki', zwraca 0.0.
    """
    try:
        tax_node = card.query_selector('[data-testid="taxes-and-charges"]')
        if not tax_node:
            return 0.0
        txt = tax_node.inner_text().replace("\xa0", " ").lower().strip()
        if "zawiera" in txt or "included" in txt or "includes" in txt:
            return 0.0
        if "+" in txt or "podatk" in txt or "opłat" in txt or "tax" in txt or "charge" in txt:
            val = _parse_amount(txt)
            if 5.0 <= val <= 500.0:
                return val
    except Exception:
        pass
    return 0.0


def _extract_price_details(card) -> tuple[float, float, float]:
    """
    Zwraca krotkę: (cena_całkowita_brutto, cena_bazowa, doliczone_podatki).
    """
    base_val = 0.0
    try:
        # 1. Główny kontener aktualnej ceny (ignoruje przekreśloną cenę pierwotną)
        price_node = card.query_selector('[data-testid="price-and-discounted-price"]')
        if price_node:
            base_val = _parse_amount(price_node.inner_text())

        # 2. Zapasowe selektory stawek
        if base_val < 90.0:
            for sel in ['[data-testid="price"]', '[data-testid="availability-rate-information"]']:
                node = card.query_selector(sel)
                if node:
                    candidate = _parse_amount(node.inner_text())
                    if 90.0 <= candidate <= 2500.0:
                        base_val = candidate
                        break

        if 90.0 <= base_val <= 2500.0:
            taxes = _extract_taxes(card)
            total_val = round(base_val + taxes, 2)
            return total_val, base_val, taxes
    except Exception:
        pass

    return 0.0, 0.0, 0.0


def _classify_property_type(name: str, adults: int = 2) -> str:
    """Precyzyjnie rozróżnia hotele od apartamentów."""
    name_lower = name.lower()
    hotel_indicators = [
        "hotel", "hola", "marriott", "mercure", "courtyard", "radisson",
        "accor", "willa", "villa", "boutique", "dworek", "spa", "resort",
        "batory", "blick", "hotton", "antares", "marynarz", "pensjonat",
        "inn", "relais", "bed & breakfast", "aparthotel"
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
    Pobiera aktualne ceny brutto z Booking.com dla Gdyni (1 os. lub 2 os.).
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
                timezone_id="Europe/Warsaw",
                extra_http_headers={
                    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7"
                }
            )

            context.add_cookies([
                {"name": "selected_currency", "value": "PLN", "domain": ".booking.com", "path": "/"},
                {"name": "b_lang", "value": "pl", "domain": ".booking.com", "path": "/"},
                {"name": "user_country", "value": "pl", "domain": ".booking.com", "path": "/"}
            ])

            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'languages', { get: () => ['pl-PL', 'pl', 'en-US', 'en'] });
            """)

            page = context.new_page()

            # sb_price_type=total wymusza prezentację ceny brutto (z podatkami i opłatami)
            url = (
                f"https://www.booking.com/searchresults.pl.html?"
                f"ss=Gdynia&dest_id=-501414&dest_type=city"
                f"&checkin={checkin_date}&checkout={checkout_date}"
                f"&group_adults={adults}&no_rooms=1&group_children=0"
                f"&selected_currency=PLN&lang=pl&sb_price_type=total"
            )

            for attempt in range(1, 3):
                try:
                    page.goto(url, timeout=35000, wait_until="domcontentloaded")
                except PlaywrightTimeoutError:
                    pass

                try:
                    page.wait_for_selector("body", timeout=8000, state="attached")
                    break
                except Exception:
                    time.sleep(1.0)

            time.sleep(2.0)

            # Zamknięcie nakładek cookies / logowania Genius
            for btn_sel in [
                'button#onetrust-accept-btn-handler',
                'button[aria-label="Odwrzuć"]',
                'button[aria-label="Odrzuć"]',
                'button[aria-label="Zamknij"]',
                'button[data-testid="header-sign-in-dismiss-button"]'
            ]:
                try:
                    b = page.query_selector(btn_sel)
                    if b and b.is_visible():
                        b.click()
                        time.sleep(0.3)
                except Exception:
                    pass

            # Przewijanie (Infinite Scroll)
            try:
                page.evaluate("() => { const el = document.body || document.documentElement; if (el) window.scrollTo(0, el.scrollHeight); }")
                time.sleep(1.5)
                page_height = page.evaluate("() => (document.body ? document.body.scrollHeight : 2500)")
                for s in range(1, 6):
                    page.evaluate(f"window.scrollTo(0, {int(page_height * (s / 5))});")
                    time.sleep(0.35)
            except Exception:
                pass

            try:
                page.wait_for_selector('[data-testid="property-card"]', timeout=10000, state="attached")
            except Exception:
                pass

            cards = page.query_selector_all('[data-testid="property-card"]')
            total_cards_seen = len(cards)
            print(f"[DEBUG SCRAPER] Znaleziono kart ({adults} os., {checkin_date}): {total_cards_seen}", flush=True)

            for card in cards:
                try:
                    title_elem = card.query_selector('[data-testid="title"]')
                    if not title_elem:
                        continue
                    name = title_elem.inner_text().strip()

                    # Wykluczamy nasz własny obiekt z listy konkurencji
                    if "baltic hotel" in name.lower():
                        continue

                    card_full_text = card.inner_text().lower()
                    if any(bad in card_full_text for bad in strict_exclusions):
                        continue

                    total_price, base_price, taxes_added = _extract_price_details(card)
                    if 90.0 <= total_price <= 2500.0:
                        prop_type = _classify_property_type(name, adults=adults)
                        details_list.append({
                            "hotel": name,
                            "price": total_price,
                            "base_price": base_price,
                            "taxes_added": taxes_added,
                            "type": prop_type
                        })

                        if "hola" in name.lower() and found_hola_price is None:
                            found_hola_price = total_price
                except Exception:
                    continue

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
            "checkin_date": checkin_date,
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
            "message": f"Pobrano {len(unique_details)} ofert brutto dla {adults} os. na {checkin_date} (Hotele: {len(hotel_prices)}, Apartamenty: {len(apt_prices)})."
        }

    except Exception as e:
        return _get_fallback_prices(adults=adults, reason=f"Błąd: {str(e)}")


if __name__ == "__main__":
    res = fetch_gdynia_competitor_prices(adults=2)
    print(res["message"])
    print("HOLA GDYNIA:", res.get("hola_price"))
    for row in res["details"][:10]:
        print(f" - {row['hotel']:<45} | Brutto: {row['price']:.0f} PLN (baza: {row['base_price']:.0f}, podatek: {row['taxes_added']:.0f})")
