"""
pricing_engine.py
-----------------
Silnik Revenue Management dla Baltic Hotel (Standard 3★).
Wykorzystuje:
- Zbalansowaną wagę benchmarku: HOLA Gdynia (35%) + Mediana rynku 3★ (65%)
- Fallback do czystej mediany 3★ przy braku oferty HOLA
- Ciągłą logistyczną krzywą rzadkości (punkt równowagi: ~77% obłożenia z 27 pokoi)
- Model wygasania podaży w ujęciu godzinowym (Time Decay)
- Twardy próg rentowności (Floor Price)
"""

import math
import statistics
from typing import List, Dict, Any, Optional

TOTAL_ROOMS: int = 27
TARGET_OCCUPANCY_RATE: float = 0.77  # Cel: ~77% obłożenia (sprzedane 20-22 pokoje, wolne max 5-7 pokoi)
DEFAULT_FLOOR_PRICE: float = 150.0   # Domyślny twardy próg minimalny


def _get_percentile(data: List[float], p: float) -> float:
    """Wylicza interpolowany percentyl z posortowanej listy."""
    k = (len(data) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    return data[int(f)] * (c - k) + data[int(c)] * (k - f)


def _calculate_3star_market_stats(competitor_prices: List[float], guests_count: int = 2) -> Dict[str, float]:
    """Wyznacza statystyki rynkowe dla segmentu 3-gwiazdkowego."""
    fallback_median = 230.0 if guests_count == 1 else 280.0
    if not competitor_prices:
        return {"p25": fallback_median * 0.85, "median_3star": fallback_median, "p75": fallback_median * 1.25}

    clean = sorted([p for p in competitor_prices if 90.0 <= p <= 1800.0])
    if not clean:
        return {"p25": fallback_median * 0.85, "median_3star": fallback_median, "p75": fallback_median * 1.25}

    return {
        "p25": round(_get_percentile(clean, 0.25), 2),
        "median_3star": round(_get_percentile(clean, 0.50), 2),
        "p75": round(_get_percentile(clean, 0.75), 2)
    }


def calculate_room_price(
    free_rooms: int,
    current_hour: int,
    competitor_prices: List[float],
    floor_price: float = DEFAULT_FLOOR_PRICE,
    hola_price: Optional[float] = None,
    competitor_details: Optional[List[Dict[str, Any]]] = None,
    guests_count: int = 2
) -> Dict[str, Any]:
    """
    Kalkuluje optymalną cenę pokoju 1-osobowego lub 2-osobowego w standardzie 3★.
    Wagi bazy: HOLA Gdynia 35%, Mediana rynku 65%.
    """
    # 1. Walidacja wejścia
    free_rooms = max(0, min(TOTAL_ROOMS, int(free_rooms)))
    current_hour = max(0, min(23, int(current_hour)))
    floor_price = max(80.0, float(floor_price))

    sold_rooms = TOTAL_ROOMS - free_rooms
    occupancy_rate = sold_rooms / TOTAL_ROOMS

    # 2. Wykrywanie ceny HOLA Gdynia w szczegółach (jeśli nie przekazano wprost)
    if hola_price is None and competitor_details:
        for item in competitor_details:
            if "hola" in item.get("hotel", "").lower():
                hola_price = float(item.get("price", 0.0))
                break

    market_stats = _calculate_3star_market_stats(competitor_prices, guests_count=guests_count)
    median_3star = market_stats["median_3star"]

    # 3. Ustalenie bazy wyceny (HOLA 35%, Rynek 65%)
    is_hola_anchored = False
    if hola_price and 100.0 <= hola_price <= 1200.0:
        base_price = (hola_price * 0.25) + (median_3star * 0.75)
        is_hola_anchored = True
    else:
        base_price = median_3star

    # 4. Ciągła logistyczna krzywa rzadkości wokół celu ~77% obłożenia
    delta_occ = occupancy_rate - TARGET_OCCUPANCY_RATE
    scarcity_factor = (math.exp(6.0 * delta_occ) - 1.0) / (math.exp(6.0 * delta_occ) + 1.0)
    occ_multiplier = 1.0 + (scarcity_factor * 0.28)

    # 5. Presja czasu i model tempa rezerwacji
    target_rooms_needed = max(0, free_rooms - 7)
    hours_left = max(1.0, 24.0 - float(current_hour))
    required_velocity = target_rooms_needed / hours_left

    if current_hour < 14:
        time_multiplier = 1.04
    elif 14 <= current_hour < 18:
        time_multiplier = 1.00
    elif 18 <= current_hour < 21:
        time_multiplier = 0.96 if required_velocity > 0.5 else 1.00
    else:  # 21:00 - 23:00 (Późny wieczór)
        if target_rooms_needed == 0:
            time_multiplier = 0.95
        else:
            penalty = min(0.22, required_velocity * 0.08)
            time_multiplier = max(0.78, 1.0 - penalty)

    # 6. Wyznaczenie ceny końcowej i twardy próg minimalny
    raw_optimal_price = base_price * occ_multiplier * time_multiplier

    floor_triggered = False
    if raw_optimal_price < floor_price:
        final_price = floor_price
        floor_triggered = True
    else:
        final_price = raw_optimal_price

    sugerowana_cena = int(round(final_price))

    # 7. Dynamiczne widełki cenowe
    iqr = max(20.0, market_stats["p75"] - market_stats["p25"])
    spread = min(35.0, max(15.0, iqr * 0.25))
    widelki_min = int(max(floor_price, round(sugerowana_cena - spread)))
    widelki_max = int(round(sugerowana_cena + spread))

    # 8. Uzasadnienie biznesowe
    diag = [f"Pokój: {guests_count}-osobowy | Standard: 3★"]
    if is_hola_anchored:
        diag.append(f"Punkt referencyjny: HOLA Gdynia ({hola_price:.0f} PLN, waga 35%) + Mediana rynku ({median_3star:.0f} PLN, waga 65%)")
    else:
        diag.append(f"Fallback benchmarku: Mediana rynku ({median_3star:.0f} PLN, brak oferty HOLA)")

    diag.append(f"Obłożenie: {occupancy_rate * 100:.1f}% ({sold_rooms}/{TOTAL_ROOMS} pokoi, wolnych: {free_rooms})")

    if delta_occ >= 0:
        diag.append("Status: Cel 75-80% OSIĄGNIĘTY (aktywna premia rzadkości).")
    else:
        diag.append(f"Status: Poniżej celu 75% (brakuje {target_rooms_needed} pokoi do progu optymalnego).")

    if current_hour >= 21 and delta_occ < 0:
        diag.append(f"Presja czasu: Godz. {current_hour}:00, popyt nocny wymaga upustu.")

    if floor_triggered:
        diag.append(f"BLOKADA MARŻY: Zadziałał twardy próg minimalny {floor_price:.0f} PLN.")

    return {
        "cena_sugerowana": sugerowana_cena,
        "widelki_min": widelki_min,
        "widelki_max": widelki_max,
        "uzasadnienie_decyzji": " | ".join(diag),
        "oblozenie_procent": round(occupancy_rate * 100, 1),
        "srednia_konkurencji": median_3star,
        "base_price": round(base_price, 2),
        "hola_price": hola_price,
        "is_hola_anchored": is_hola_anchored,
        "guests_count": guests_count
    }
