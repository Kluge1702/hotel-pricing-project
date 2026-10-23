"""
app.py
------
Interfejs Streamlit dla Baltic Hotel Gdynia (Standard 3★).
Obsługuje wycenę pokoi 1-osobowych oraz 2-osobowych z niezależnym buforowaniem w sesji.
"""

import os
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st

from pricing_engine import calculate_room_price, TOTAL_ROOMS
from scraper import fetch_gdynia_competitor_prices

icon_path = "app_icon.png" if os.path.exists("app_icon.png") else "🏨"
st.set_page_config(
    page_title="Baltic Hotel 3★ – Panel Wyceny",
    page_icon=icon_path,
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .main-header { font-size: 28px; font-weight: bold; color: #1F497D; margin-bottom: 5px; }
    .sub-header { font-size: 15px; color: #555555; margin-bottom: 25px; }
    .metric-card { background-color: #F0F4F8; border-radius: 10px; padding: 18px; text-align: center; border-left: 5px solid #2E6B38; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .metric-label { font-size: 13px; color: #555555; text-transform: uppercase; font-weight: 600; }
    .metric-value-main { font-size: 38px; font-weight: bold; color: #2E6B38; }
    .metric-value-sub { font-size: 24px; font-weight: bold; color: #1F497D; }
    .badge-hola { background-color: #E8F5E9; color: #2E7D32; padding: 6px 12px; border-radius: 6px; font-weight: bold; border: 1px solid #C8E6C9; }
    .badge-fallback { background-color: #FFF3E0; color: #E65100; padding: 6px 12px; border-radius: 6px; font-weight: bold; border: 1px solid #FFE0B2; }
    .time-badge { font-size: 12px; color: #666666; margin-top: 4px; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">🏨 Baltic Hotel Gdynia (Standard 3★) – Dynamiczna Wycena</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Optymalizacja stawek w oparciu o HOLA Gdynia (35%), rynek Gdyni (65%) oraz obłożenie hotelu</div>', unsafe_allow_html=True)

# ==============================================================================
# 1. PAMIĘĆ SESJI
# ==============================================================================
default_checkin = datetime.today() + timedelta(days=1)

if "checkin_date" not in st.session_state:
    st.session_state["checkin_date"] = default_checkin

# Osobne kontenery dla 1 osoby i 2 osób
if "market_data_1" not in st.session_state:
    st.session_state["market_data_1"] = None
if "market_data_2" not in st.session_state:
    st.session_state["market_data_2"] = None

if "last_scrape_time_1" not in st.session_state:
    st.session_state["last_scrape_time_1"] = None
if "last_scrape_time_2" not in st.session_state:
    st.session_state["last_scrape_time_2"] = None

# ==============================================================================
# 2. PASEK BOCZNY – SEKCJA A: PARAMETRY RYNKU (Z WYBOREM 1 OS. / 2 OS.)
# ==============================================================================
st.sidebar.header("🌐 Rynek Konkurencji")

checkin_date = st.sidebar.date_input(
    "Data rezerwacji (Check-in):",
    value=st.session_state["checkin_date"],
    min_value=datetime.today()
)
checkout_date = checkin_date + timedelta(days=1)

if checkin_date != st.session_state["checkin_date"]:
    st.session_state["checkin_date"] = checkin_date
    st.session_state["market_data_1"] = None
    st.session_state["market_data_2"] = None

# Przełącznik 1 os. vs 2 os.
guests_count = st.sidebar.radio(
    "Typ pokoju / Liczba gości:",
    options=[1, 2],
    index=1,
    format_func=lambda x: f"Pokój 1-osobowy (1 os.)" if x == 1 else f"Pokój 2-osobowy (2 os.)",
    horizontal=True
)

btn_refresh_market = st.sidebar.button("🔄 Pobierz / Odśwież rynek Booking.com", use_container_width=True)

market_key = f"market_data_{guests_count}"
time_key = f"last_scrape_time_{guests_count}"

# Pobranie danych jeśli brak w pamięci lub kliknięto odświeżenie
if st.session_state[market_key] is None or btn_refresh_market:
    with st.spinner(f"🔍 Skanowanie rynku Gdyni dla {guests_count} os. (Booking.com)..."):
        st.session_state[market_key] = fetch_gdynia_competitor_prices(
            checkin_date=checkin_date.strftime("%Y-%m-%d"),
            checkout_date=checkout_date.strftime("%Y-%m-%d"),
            adults=guests_count
        )
        st.session_state[time_key] = datetime.now().strftime("%H:%M:%S")

comp_data = st.session_state[market_key]

if st.session_state[time_key]:
    st.sidebar.markdown(f'<div class="time-badge">🕒 Ostatnie pobranie ({guests_count} os.): <b>{st.session_state[time_key]}</b></div>', unsafe_allow_html=True)

st.sidebar.markdown("---")

# ==============================================================================
# 3. PASEK BOCZNY – SEKCJA B: FORMULARZ WYCENY BALTIC HOTEL
# ==============================================================================
st.sidebar.header("⚙️ Parametry Baltic Hotel")

default_floor = 130.0 if guests_count == 1 else 150.0

with st.sidebar.form("pricing_form"):
    free_rooms = st.slider(
        "Liczba WOLNYCH pokoi (z 27):",
        min_value=0,
        max_value=TOTAL_ROOMS,
        value=8,
        help="Wybierz ile pokoi w hotelu pozostało wolnych na tę dobę."
    )

    selected_hour = st.slider(
        "Godzina analizy (0 - 23):",
        min_value=0,
        max_value=23,
        value=datetime.now().hour,
        help="Aktualna godzina analizy (wpływa na presję czasową do północy)."
    )

    floor_price = st.number_input(
        "Twardy próg MINIMALNY (PLN):",
        min_value=80.0,
        max_value=300.0,
        value=default_floor,
        step=10.0,
        help=f"Minimalna stawka pokoju (domyślnie {default_floor:.0f} PLN dla {guests_count} os.)."
    )

    btn_recalculate = st.form_submit_button("⚡ PRZELICZ CENĘ (błyskawicznie)", use_container_width=True, type="primary")

# ==============================================================================
# 4. PRZELICZENIE W PAMIĘCI
# ==============================================================================
pricing_result = calculate_room_price(
    free_rooms=free_rooms,
    current_hour=selected_hour,
    competitor_prices=comp_data["prices"],
    floor_price=floor_price,
    hola_price=comp_data.get("hola_price"),
    competitor_details=comp_data.get("details"),
    guests_count=guests_count
)

# ==============================================================================
# 5. PREZENTACJA WYNIKÓW
# ==============================================================================
col_stat1, col_stat2 = st.columns([3, 1])
with col_stat1:
    if comp_data["source"] == "booking_live":
        st.success(f"✅ {comp_data['message']}")
    else:
        st.warning(f"⚠️ {comp_data['message']}")

with col_stat2:
    if pricing_result["is_hola_anchored"]:
        st.markdown(f'<div class="badge-hola">🎯 HOLA (35%): {pricing_result["hola_price"]:.0f} PLN</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="badge-fallback">ℹ️ Mediana rynku 3★ (100%)</div>', unsafe_allow_html=True)

st.subheader(f"📊 Wynik Wyceny – Pokój {guests_count}-osobowy (Standard 3★)")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f'<div class="metric-card"><div class="metric-label">CENA SUGEROWANA ({guests_count} OS.)</div><div class="metric-value-main">{pricing_result["cena_sugerowana"]} PLN</div></div>', unsafe_allow_html=True)
with col2:
    st.markdown(f'<div class="metric-card"><div class="metric-label">WIDEŁKI CENOWE</div><div class="metric-value-sub">{pricing_result["widelki_min"]} – {pricing_result["widelki_max"]} PLN</div></div>', unsafe_allow_html=True)
with col3:
    st.markdown(f'<div class="metric-card"><div class="metric-label">OBŁOŻENIE HOTELU</div><div class="metric-value-sub">{pricing_result["oblozenie_procent"]}%</div><small>({TOTAL_ROOMS - free_rooms}/{TOTAL_ROOMS} zajętych)</small></div>', unsafe_allow_html=True)
with col4:
    st.markdown(f'<div class="metric-card"><div class="metric-label">BAZA WYCENY 3★</div><div class="metric-value-sub">{pricing_result["base_price"]:.0f} PLN</div><small>HOLA 35% + Rynek 65%</small></div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
st.info(f"💡 **Uzasadnienie decyzji cenowej:**\n\n{pricing_result['uzasadnienie_decyzji']}")
st.markdown("---")

# ==============================================================================
# 6. TABELA OFERT KONKURENCJI
# ==============================================================================
st.subheader(f"🏢 Rynek Konkurencji w Gdyni – Oferty dla {guests_count} os. (Booking.com)")
col_l, col_r = st.columns([2, 1])

with col_l:
    if "details" in comp_data and comp_data["details"]:
        df_details = pd.DataFrame(comp_data["details"])
        if "type" in df_details.columns:
            df_details = df_details[["type", "hotel", "price"]]
            df_details.columns = ["Typ Obiektu", "Nazwa Obiektu / Hotelu", "Cena za dobę (PLN)"]
        else:
            df_details = df_details[["hotel", "price"]]
            df_details.columns = ["Nazwa Obiektu / Hotelu", "Cena za dobę (PLN)"]

        df_details["Cena za dobę (PLN)"] = df_details["Cena za dobę (PLN)"].apply(lambda x: f"{x:.0f} PLN")
        st.dataframe(df_details, use_container_width=True, hide_index=True)
    else:
        df_prices = pd.DataFrame({
            "Lp.": list(range(1, len(comp_data["prices"]) + 1)),
            "Cena za dobę (PLN)": [f"{p:.0f} PLN" for p in comp_data["prices"]]
        })
        st.dataframe(df_prices, use_container_width=True, hide_index=True)

with col_r:
    st.markdown(f"**Podsumowanie rynku ({guests_count} os.):**")
    st.write(f"• **Przeanalizowano kart:** {comp_data.get('przejrzano_obiektow', 0)}")
    st.write(f"• **Pobrano stawek:** {comp_data.get('pobrano_cen', len(comp_data['prices']))}")
    if "hotel_count" in comp_data and "apt_count" in comp_data:
        st.write(f"  - Hotele: **{comp_data['hotel_count']} szt.** (śr. {comp_data.get('hotel_avg', 0):.0f} PLN)")
        st.write(f"  - Apartamenty: **{comp_data['apt_count']} szt.** (śr. {comp_data.get('apt_avg', 0):.0f} PLN)")
    st.write(f"• **Cena najniższa:** {comp_data['min_price']:.0f} PLN")
    st.write(f"• **Mediana rynkowa:** {comp_data['median_price']:.0f} PLN")
    st.write(f"• **Cena najwyższa:** {comp_data['max_price']:.0f} PLN")
