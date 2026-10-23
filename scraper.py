"""
scraper.py
----------
Niezawodny scraper Booking.com dla Gdyni.
Obsługuje dynamiczne doładowywanie ofert za pomocą przycisku "Załaduj więcej wyników",
poprawnie klasyfikuje hotele (Marriott, Mercure, HOLA itp.) oraz apartamenty 2-osobowe.
"""

import os
import sys
import subprocess
import statistics
import re
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Automatyczna instalacja Playwright i Chromium (dla Streamlit Cloud)
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


def _get_fallback_prices(reason: str = "") -> Dict[str, Any]:
    """Estymacja zapasowa w przypadku braku połączenia."""
    fallback_data = [
        {"hotel": "HOLA GDYNIA", "price": 421.0, "type": "Hotel / Obiekt"},
        {"hotel": "Courtyard by Marriott Gdynia Waterfront", "price": 344.0, "type": "Hotel / Obiekt"},
        {"hotel": "Mercure Gdynia Centrum", "price": 397.0, "type": "Hotel / Obiekt"},
        {"hotel": "Hotel Nadmorski", "price": 380.0, "type": "Hotel / Obiekt"},
        {"hotel": "Hotton Hotel", "price": 318.0, "type": "Hotel / Obiekt"},
        {"hotel": "Hotel Dom Marynarza", "price": 271.0, "type": "Hotel / Obiekt"},
        {"hotel": "Hotel Antares Gdynia", "price": 370.0, "type": "Hotel / Obiekt"},
        {"hotel": "Hotel Willa Lubicz", "price": 365.0, "type": "Hotel / Obiekt"},
        {"hotel": "Willa Pieńkowskich", "price": 314.0, "type": "Hotel / Obiekt"},
        {"hotel": "Hotel Kuracyjny Spa & Wellness", "price": 304.0, "type": "Hotel / Obiekt"},
        {"hotel": "Studio Świętojańska Centrum", "price": 250.0, "type": "Apartament 2-os."},
        {"hotel": "Apartament Marina Śródmieście", "price": 280.0, "type": "Apartament 2-os."},
        {"hotel": "SQUARE APARTMENTS GDYNIA", "price": 357.0, "type": "Apartament 2-os."},
        {"hotel": "7th Floor Rooms & Apartments", "price": 424.0, "type": "Apartament 2-os."},
    ]
    prices = [item["price"] for item in fallback_data]
    return {
        "prices": prices,
        "details": fallback_data,
        "hola_price": 421.0,
        "hotel_avg": 348.4,
        "apt_avg": 327.7,
        "hotel_count": 10,
        "apt_count": 4,
        "przejrzano_obiektow": len(fallback_data),
        "pobrano_cen": len(prices),
        "min_price": float(min(prices)),
        "avg_price": float(round(statistics.mean(prices), 2)),
        "median_price": float(round(statistics.median(prices), 2)),
        "max_price": float(max(prices)),
        "source": "fallback_estimate",
        "message": f"Użyto estymacji zapasowej. {reason}".strip()
    }


def _extract_price(card) -> float:
    """Wyciąga kwotę w PLN z karty Bookingu."""
    price_node = card.query_selector('[data-testid="price-and-discounted-price"]')
    if price_node:
        txt = price_node.inner_text().replace("\xa0", " ").strip()
        m = re.search(r'(\d[\d\s]*)\s*(?:zł|PLN)', txt)
        if m:
            clean = re.sub(r"[^\d]", "", m.group(1))
            if clean:
                return float(clean)

    card_text = card.inner_text().replace("\xa0", " ")
    all_prices = re.findall(r'(\d[\d\s]{1,6})\s*zł', card_text)
    if all_prices:
        clean = re.sub(r"[^\d]", "", all_prices[-1])
        if clean:
            val = float(clean)
            if 110.0 <= val <= 2500.0:
                return val
    return 0.0


def _classify_property_type(name: str) -> str:
    """Rozróżnia hotel/obiekt od apartamentu/studia."""
    name_lower = name.lower()
    hotel_indicators = [
        "hotel", "hola", "marriott", "mercure", "courtyard", "radisson",
        "accor", "willa", "boutique", "dworek", "spa", "resort", "batory",
        "blick", "hotton", "antares", "marynarz", "pensjonat", "inn", "relais"
    ]
    if any(h in name_lower for h in hotel_indicators):
        return "Hotel / Obiekt"
    
    return "Apartament 2-os."


def fetch_gdynia_competitor_prices(
    checkin_date: str = None,
    checkout_date: str = None,
    max_loads: int = 3  # 3 doładowania = ~75-100 ofert
) -> Dict[str, Any]:
    """
    Pobiera oferty z Booking.com rozwijając listę przyciskiem 'Załaduj więcej wyników'.
    """
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
                    "--window-size=1920,1080"
                ]
            )

            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="pl-PL",
                timezone_id="Europe/Warsaw"
            )

            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)

            page = context.new_page()

            url = (
                f"https://www.booking.com/searchresults.pl.html?"
                f"ss=Gdynia&dest_id=-501414&dest_type=city"
                f"&checkin={checkin_date}&checkout={checkout_date}"
                f"&group_adults=2&no_rooms=1&group_children=0"
                f"&selected_currency=PLN"
            )

            try:
                page.goto(url, timeout=35000, wait_until="domcontentloaded")
            except PlaywrightTimeoutError:
                pass

            time.sleep(2.5)

            # Zamknięcie banera cookies
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

            # Pętla klikania w "Załaduj więcej wyników"
            for load_idx in range(1, max_loads + 1):
                # Przewijamy na sam dół strony, gdzie pojawia się przycisk
                page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.2)

                # Wyszukujemy przycisk widoczny na zrzucie ekranu
                load_more_btn = None
                selectors = [
                    '//button[contains(., "Załaduj więcej")]',
                    '//button[contains(., "Load more")]',
                    'button:has-text("Załaduj więcej wyników")',
                    'span:has-text("Załaduj więcej wyników")'
                ]
                
                for sel in selectors:
                    try:
                        elem = page.query_selector(sel)
                        if elem and elem.is_visible():
                            load_more_btn = elem
                            break
                    except Exception:
                        pass

                if load_more_btn:
                    try:
                        print(f"[DEBUG] Znaleziono przycisk – klikam 'Załaduj więcej wyników' ({load_idx}/{max_loads})...")
                        load_more_btn.scroll_into_view_if_needed()
                        time.sleep(0.4)
                        load_more_btn.click()
                        time.sleep(3.0)  # Czas na doczytanie nowych kart przez Bookingu
                    except Exception as e:
                        print(f"[DEBUG] Problem z kliknięciem przycisku: {e}")
                        break
                else:
                    print("[DEBUG] Brak przycisku 'Załaduj więcej wyników' – cała lista została już rozwinięta.")
                    break

            # Płynne przewinięcie całej strony w dół, aby wszystkie załadowane karty wyrenderowały ceny
            page_height = page.evaluate("document.body.scrollHeight")
            steps = 6
            for s in range(1, steps + 1):
                page.evaluate(f"window.scrollTo(0, {int(page_height * (s / steps))});")
                time.sleep(0.3)

            # Pobranie wszystkich rozwiniętych kart
            cards = page.query_selector_all('[data-testid="property-card"]')
            total_cards_seen = len(cards)
            print(f"[DEBUG] Łącznie widocznych kart na stronie po rozwinięciu: {total_cards_seen}")

            for card in cards:
                title_elem = card.query_selector('[data-testid="title"]')
                if not title_elem:
                    continue
                name = title_elem.inner_text().strip()
                card_full_text = card.inner_text().lower()

                if any(bad in card_full_text for bad in strict_exclusions):
                    continue

                price_val = _extract_price(card)
                if 110.0 <= price_val <= 1500.0:
                    prop_type = _classify_property_type(name)
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
        if len(unique_prices) < 5:
            return _get_fallback_prices(f"Zbyt mała próba po filtracji ({len(unique_prices)}).")

        hotel_prices = [item["price"] for item in unique_details if item["type"] == "Hotel / Obiekt"]
        apt_prices = [item["price"] for item in unique_details if item["type"] == "Apartament 2-os."]

        hotel_avg = round(statistics.mean(hotel_prices), 2) if hotel_prices else round(statistics.mean(unique_prices), 2)
        apt_avg = round(statistics.mean(apt_prices), 2) if apt_prices else round(statistics.mean(unique_prices), 2)

        return {
            "prices": unique_prices,
            "details": unique_details,
            "hola_price": found_hola_price,
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
            "message": f"Pobrano {len(unique_details)} unikalnych ofert (Hotele: {len(hotel_prices)}, Apartamenty 2-os.: {len(apt_prices)})."
        }

    except Exception as e:
        return _get_fallback_prices(f"Błąd Playwright: {str(e)}")


if __name__ == "__main__":
    print("=" * 70)
    print("TEST ROZWIJANIA LISTY PRZYCISKIEM 'ZAŁADUJ WIĘCEJ WYNIKÓW'")
    print("=" * 70)
    res = fetch_gdynia_competitor_prices()
    print("-" * 70)
    print("Status:", res["message"])
    print(f"HOLA Gdynia: {res.get('hola_price')} PLN")
    print(f"Średnia Hoteli: {res.get('hotel_avg')} PLN ({res.get('hotel_count')} szt.)")
    print(f"Średnia Apartamentów 2-os.: {res.get('apt_avg')} PLN ({res.get('apt_count')} szt.)")
    print("=" * 70)
    for idx, h in enumerate(res.get("details", [])[:25], 1):
        print(f" {idx:2d}. [{h['type']:<16}] {h['hotel'][:35]:<35} : {h['price']:>4.0f} PLN")
