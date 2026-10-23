"""
scraper.py
----------
Niezawodny scraper Booking.com dla Gdyni zoptymalizowany pod Streamlit Cloud.
Wyszukuje oferty hoteli 2-4★ oraz bezpośredni benchmark HOLA Gdynia.
"""

import os
import sys
import subprocess
import statistics
import re
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Automatyczna weryfikacja Chromium
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
    """Realistyczna estymacja zapasowa w przypadku blokady Bookingu."""
    fallback_data = [
        {"hotel": "HOLA GDYNIA", "price": 341.0},
        {"hotel": "Hotel Mercure Gdynia Centrum", "price": 290.0},
        {"hotel": "Hotel Courtyard by Marriott Gdynia", "price": 360.0},
        {"hotel": "Hotel Nadmorski", "price": 330.0},
        {"hotel": "Hotel Hotton", "price": 250.0},
        {"hotel": "Hotel Batory", "price": 220.0},
        {"hotel": "Hotel Blick", "price": 270.0},
        {"hotel": "Hotel Willa Baltica", "price": 310.0},
    ]
    prices = [item["price"] for item in fallback_data]
    return {
        "prices": prices,
        "details": fallback_data,
        "hola_price": 341.0,
        "przejrzano_obiektow": len(fallback_data),
        "pobrano_cen": len(prices),
        "min_price": float(min(prices)),
        "avg_price": float(round(statistics.mean(prices), 2)),
        "median_price": float(round(statistics.median(prices), 2)),
        "max_price": float(max(prices)),
        "source": "fallback_estimate",
        "message": f"Użyto estymacji zapasowej. {reason}".strip()
    }


def fetch_gdynia_competitor_prices(
    checkin_date: str = None,
    checkout_date: str = None,
    max_pages: int = 2
) -> Dict[str, Any]:
    """
    Pobiera aktualne ceny hoteli w Gdyni z Booking.com.
    """
    if not checkin_date:
        today = datetime.today()
        checkin_dt = today + timedelta(days=1)
        checkout_dt = checkin_dt + timedelta(days=1)
        checkin_date = checkin_dt.strftime("%Y-%m-%d")
        checkout_date = checkout_dt.strftime("%Y-%m-%d")

    details_list: List[Dict[str, Any]] = []
    total_cards_seen = 0
    found_hola_price = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--window-size=1920,1080"
                ]
            )

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="pl-PL",
                timezone_id="Europe/Warsaw",
                extra_http_headers={
                    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
                    "Sec-Ch-Ua-Mobile": "?0",
                    "Sec-Ch-Ua-Platform": '"Windows"',
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1"
                }
            )

            page = context.new_page()

            # Maskowanie flag automatyzacji w JS
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.navigator.chrome = { runtime: {} };
            """)

            for page_num in range(max_pages):
                offset = page_num * 25
                # Precyzyjny URL z dest_id=-501414 gwarantujący wejście w wyniki dla Gdyni
                url = (
                    f"https://www.booking.com/searchresults.pl.html?"
                    f"ss=Gdynia&dest_id=-501414&dest_type=city"
                    f"&checkin={checkin_date}&checkout={checkout_date}"
                    f"&group_adults=2&no_rooms=1&group_children=0"
                    f"&offset={offset}&nflt=class%3D2%3Bclass%3D3%3Bclass%3D4"
                )

                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                except PlaywrightTimeoutError:
                    pass

                # Aktywne czekanie na pojawienie się kart obiektów (max 15 sek)
                try:
                    page.wait_for_selector('[data-testid="property-card"]', timeout=15000, state="attached")
                except Exception:
                    pass

                # Zamykanie banera cookies / popupów
                try:
                    cookie_btn = page.query_selector(
                        'button[id="onetrust-accept-btn-handler"], '
                        'button[id="onetrust-reject-all-handler"], '
                        'button[aria-label="Odwrzuć"]'
                    )
                    if cookie_btn:
                        cookie_btn.click()
                        time.sleep(0.5)
                except Exception:
                    pass

                # Lekkie przewinięcie, aby doładować elementy w widoku
                page.evaluate("window.scrollBy(0, 1000);")
                time.sleep(1.0)

                cards = page.query_selector_all('[data-testid="property-card"]')
                total_cards_seen += len(cards)

                page_found = 0
                for card in cards:
                    # 1. Pobranie nazwy hotelu
                    title_elem = card.query_selector('[data-testid="title"]')
                    if not title_elem:
                        continue
                    hotel_name = title_elem.inner_text().strip()

                    # 2. Pobranie ceny (obsługa głównego oraz alternatywnych selektorów)
                    price_elem = card.query_selector(
                        '[data-testid="price-and-discounted-price"], '
                        '[data-testid="price"], '
                        '.b87c397a13'
                    )
                    if not price_elem:
                        continue

                    raw_price = price_elem.inner_text().strip()
                    cleaned_val = re.sub(r"[^\d]", "", raw_price)

                    if cleaned_val:
                        try:
                            val = float(cleaned_val)
                            # Walidacja logicznego przedziału cenowego za dobę
                            if 100.0 <= val <= 3000.0:
                                details_list.append({"hotel": hotel_name, "price": val})
                                page_found += 1

                                # Detekcja HOLA Gdynia
                                if "hola" in hotel_name.lower() and found_hola_price is None:
                                    found_hola_price = val
                        except ValueError:
                            pass

                # Jeśli na pierwszej stronie nie znaleziono kart, przerywamy pętlę
                if len(cards) == 0 or page_found == 0:
                    break

            browser.close()

        # Deduplikacja wyników
        seen = set()
        unique_details = []
        for item in details_list:
            key = (item["hotel"], item["price"])
            if key not in seen:
                seen.add(key)
                unique_details.append(item)

        unique_prices = sorted([item["price"] for item in unique_details])

        if len(unique_prices) < 3:
            return _get_fallback_prices(f"Booking zwrócił zbyt mało wyników ({len(unique_prices)}).")

        return {
            "prices": unique_prices,
            "details": unique_details,
            "hola_price": found_hola_price,
            "przejrzano_obiektow": total_cards_seen,
            "pobrano_cen": len(unique_details),
            "min_price": float(min(unique_prices)),
            "avg_price": float(round(statistics.mean(unique_prices), 2)),
            "median_price": float(round(statistics.median(unique_prices), 2)),
            "max_price": float(max(unique_prices)),
            "source": "booking_live",
            "message": f"Pobrano {len(unique_details)} aktualnych ofert z Booking.com dla Gdyni."
        }

    except Exception as e:
        return _get_fallback_prices(f"Błąd Playwright: {str(e)}")


if __name__ == "__main__":
    print("Testuję scraper...")
    res = fetch_gdynia_competitor_prices()
    print("Status:", res["message"])
    print("Cena HOLA:", res.get("hola_price"))
    print("Liczba hoteli:", res["pobrano_cen"])
