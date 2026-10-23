"""
app.py
------
Interfejs Streamlit dla Baltic Hotel Gdynia (Standard 3★).
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
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">🏨 Baltic Hotel Gdynia (Standard 3★) – Dynamiczna Wycena</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Optymalizacja stawek dobowych w oparciu o obłożenie, rynek Gdyni oraz benchmark HOLA Gdynia (3★)</div>', unsafe_allow_html=True)

st.sidebar.header("⚙️ Parametry Wyceny")

default_checkin = datetime.today() + timedelta(days=1)
checkin_date = st.sidebar.date_input("Data rezerwacji (Check-in):", value=default_checkin, min_value=datetime.today())
checkout_date = checkin_date + timedelta(days=1)

free_rooms = st.sidebar.slider("Liczba WOLNYCH pokoi (z 27):", min_value=0, max_value=TOTAL_ROOMS, value=8)
selected_hour = st.sidebar.slider("Godzina analizy (0 - 23):", min_value=0, max_value=23, value=datetime.now().hour)
floor_price = st.sidebar.number_input("Twardy próg MINIMALNY (PLN):", min_value=100.0, max_value=300.0, value=150.0, step=10.0)

st.sidebar.markdown("---")
refresh_market_data = st.sidebar.button("🔄 Odśwież dane z Booking.com", use_container_width=True)

@st.cache_data(ttl=1800)
def get_cached_competitor_data(in_date: str, out_date: str):
    return fetch_gdynia_competitor_prices(checkin_date=in_date, checkout_date=out_date)

if refresh_market_data:
    st.cache_data.clear()

with st.spinner("Pobieranie aktualnych cen konkurencji z Booking.com..."):
    comp_data = get_cached_competitor_data(
        in_date=checkin_date.strftime("%Y-%m-%d"),
        out_date=checkout_date.strftime("%Y-%m-%d")
    )

# Wyliczenie ceny z uwzględnieniem danych HOLA Gdynia
pricing_result = calculate_room_price(
    free_rooms=free_rooms,
    current_hour=selected_hour,
    competitor_prices=comp_data["prices"],
    floor_price=floor_price,
    hola_price=comp_data.get("hola_price"),
    competitor_details=comp_data.get("details")
)

# Status pobierania
col_stat1, col_stat2 = st.columns([3, 1])
with col_stat1:
    if comp_data["source"] == "booking_live":
        st.success(f"✅ {comp_data['message']}")
    else:
        st.warning(f"⚠️ {comp_data['message']}")

with col_stat2:
    if pricing_result["is_hola_anchored"]:
        st.markdown(f'<div class="badge-hola">🎯 HOLA Gdynia: {pricing_result["hola_price"]:.0f} PLN</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="badge-fallback">ℹ️ Mediana rynku 3★ (Fallback)</div>', unsafe_allow_html=True)

st.subheader("📊 Wynik Optymalizacji Ceny (Standard 3★)")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f'<div class="metric-card"><div class="metric-label">CENA SUGEROWANA</div><div class="metric-value-main">{pricing_result["cena_sugerowana"]} PLN</div></div>', unsafe_allow_html=True)
with col2:
    st.markdown(f'<div class="metric-card"><div class="metric-label">WIDEŁKI CENOWE</div><div class="metric-value-sub">{pricing_result["widelki_min"]} – {pricing_result["widelki_max"]} PLN</div></div>', unsafe_allow_html=True)
with col3:
    st.markdown(f'<div class="metric-card"><div class="metric-label">OBŁOŻENIE HOTELU</div><div class="metric-value-sub">{pricing_result["oblozenie_procent"]}%</div><small>({TOTAL_ROOMS - free_rooms}/{TOTAL_ROOMS} zajętych)</small></div>', unsafe_allow_html=True)
with col4:
    st.markdown(f'<div class="metric-card"><div class="metric-label">BAZA WYCENY 3★</div><div class="metric-value-sub">{pricing_result["base_price"]:.0f} PLN</div><small>Punkt referencyjny</small></div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
st.info(f"💡 **Uzasadnienie decyzji cenowej:**\n\n{pricing_result['uzasadnienie_decyzji']}")
st.markdown("---")

st.subheader("🏢 Przejrzany Rynek Konkurencji w Gdyni (Booking.com)")
col_l, col_r = st.columns([2, 1])

with col_l:
    if "details" in comp_data and comp_data["details"]:
        df_details = pd.DataFrame(comp_data["details"])
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
    st.markdown("**Podsumowanie rynku:**")
    st.write(f"• **Przeanalizowano kart:** {comp_data.get('przejrzano_obiektow', 0)}")
    st.write(f"• **Pobrano stawek:** {comp_data.get('pobrano_cen', len(comp_data['prices']))}")
    st.write(f"• **Cena najniższa:** {comp_data['min_price']:.0f} PLN")
    st.write(f"• **Mediana rynkowa (3★):** {comp_data['median_price']:.0f} PLN")
    st.write(f"• **Cena najwyższa:** {comp_data['max_price']:.0f} PLN")