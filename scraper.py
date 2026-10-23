"""
scraper.py
----------
Scraper ofert Booking.com w Gdyni z detekcją obiektu referencyjnego HOLA Gdynia.
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
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

_ensure_playwright_installed()
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def _get_fallback_prices(reason: str = "") -> Dict[str, Any]:
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
        "przejrzano_obiektow": 0,
        "pobrano_cen": len(prices),
        "min_price": float(min(prices)),
        "avg_price": float(round(statistics.mean(prices), 2)),
        "median_price": float(round(statistics.median(prices), 2)),
        "max_price": float(max(prices)),
        "source": "fallback_estimate",
        "message": f"Użyto estymacji zapasowej. {reason}".strip()
    }


def fetch_gdynia_competitor_prices(checkin_date: str = None, checkout_date: str = None, max_pages: int = 2) -> Dict[str, Any]:
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
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-setuid-sandbox"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                locale="pl-PL"
            )
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            for page_num in range(max_pages):
                offset = page_num * 25
                url = (
                    f"https://www.booking.com/searchresults.pl.html?"
                    f"ss=Gdynia&checkin={checkin_date}&checkout={checkout_date}"
                    f"&group_adults=2&no_rooms=1&offset={offset}"
                    f"&nflt=class%3D2%3Bclass%3D3%3Bclass%3D4%3Breview_score%3D75"
                )

                try:
                    page.goto(url, timeout=18000, wait_until="commit")
                except PlaywrightTimeoutError:
                    pass

                time.sleep(2)
                try:
                    btn = page.query_selector('button[id="onetrust-accept-btn-handler"], button[aria-label="Odwrzuć"]')
                    if btn:
                        btn.click()
                except Exception:
                    pass

                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2);")
                time.sleep(1)

                cards = page.query_selector_all('[data-testid="property-card"]')
                total_cards_seen += len(cards)

                found = 0
                for card in cards:
                    t_el = card.query_selector('[data-testid="title"]')
                    p_el = card.query_selector('[data-testid="price-and-discounted-price"]')
                    if t_el and p_el:
                        name = t_el.inner_text().strip()
                        cleaned = re.sub(r"[^\d]", "", p_el.inner_text())
                        if cleaned:
                            try:
                                val = float(cleaned)
                                if 100.0 <= val <= 2500.0:
                                    details_list.append({"hotel": name, "price": val})
                                    found += 1
                                    if "hola" in name.lower() and found_hola_price is None:
                                        found_hola_price = val
                            except ValueError:
                                pass

                if len(cards) == 0 or found == 0:
                    break

            browser.close()

        # Odrzucanie duplikatów
        unique_details = []
        seen = set()
        for item in details_list:
            key = (item["hotel"], item["price"])
            if key not in seen:
                seen.add(key)
                unique_details.append(item)

        unique_prices = sorted([item["price"] for item in unique_details])
        if len(unique_prices) < 3:
            return _get_fallback_prices(f"Zbyt mało pobranych stawek ({len(unique_prices)}).")

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