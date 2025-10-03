import math
import os
import html
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st

# ==========================================
# App Title (UI in Romanian)
# ==========================================
st.title("Jurnal de evenimente — filtru staționare")

# ==========================================
# Config / Constants (comments in English)
# ==========================================
FM_API_BASE = "https://api.fm-track.com"
EVENTS_BASE = "http://192.168.88.175:9877/api"
APP_TZ = ZoneInfo("Europe/Bucharest")  # default display timezone

# ==========================================
# Sidebar — Romanian labels
# ==========================================

# API key (kept, used for vehicle list)
if "api_key_cache" not in st.session_state:
    st.session_state.api_key_cache = None

api_key = st.sidebar.text_input("Cheie API", type="password")

# User ID selector for Events API
user_id = st.sidebar.selectbox(
    "Utilizator (x-user-id)",
    options=["user_1", "user_2"],
    index=0,
)

# Date range (entered in local TZ; converted to UTC for requests)
local_today = datetime.now(APP_TZ).date()
from_date = st.sidebar.date_input("De la", local_today)
to_date = st.sidebar.date_input("Până la", local_today)

# Stationary filter 0–99 minutes (integer only)
stationary_under = st.sidebar.number_input(
    "Staționare sub (minute)", min_value=0, max_value=99, step=1, value=0
)

# Optional display timezone
user_tz_name = st.sidebar.text_input("Fus orar de afișare (IANA)", value="Europe/Bucharest")
try:
    display_tz = ZoneInfo(user_tz_name)
except Exception:
    st.sidebar.warning("Fus orar invalid. Se folosește Europe/Bucharest.")
    display_tz = APP_TZ

# Validate date range
if to_date < from_date:
    st.sidebar.error("Data 'Până la' nu poate fi anterioară lui 'De la'.")
    st.stop()

# ==========================================
# Helpers (comments in English)
# ==========================================

def to_iso_z(dt: datetime) -> str:
    """Return ISO 8601 UTC string with Z suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def fmt_dt_local(dt_str: Optional[str]) -> Optional[str]:
    dt = parse_iso(dt_str)
    if not dt:
        return None
    return dt.astimezone(display_tz).strftime("%Y-%m-%d %H:%M:%S")


def join_address(addr: Dict[str, Any]) -> str:
    """Concatenate address parts similar to trips view."""
    if not isinstance(addr, dict):
        return ""
    parts = [
        addr.get("street"),
        addr.get("house_number"),
        addr.get("locality"),
        # prefer region, fallback to county
        addr.get("region") or addr.get("county"),
        addr.get("country"),
    ]
    return ", ".join([p for p in parts if p])


def safe_km(val) -> float:
    """Convert meters (possibly None/str) to km with 3 decimals; fallback to 0.0."""
    try:
        return round(float(val) / 1000.0, 3)
    except (TypeError, ValueError):
        return 0.0


def build_tooltip_html(row: pd.Series) -> str:
    """Build an HTML tooltip from all row key/value pairs."""
    parts: List[str] = []
    for k, v in row.items():
        key = html.escape(str(k))
        val = "" if v is None else html.escape(str(v))
        parts.append(f"<b>{key}</b>: {val}")
    return "<br/>".join(parts)

# ==========================================
# Networking (comments in English)
# ==========================================

@st.cache_data(show_spinner=False, ttl=300)
def get_session(api_key: str) -> requests.Session:
    s = requests.Session()
    s.params = {"version": 1, "api_key": api_key}
    s.headers.update({"Accept": "application/json"})
    return s


def handle_response(resp: requests.Response, context: str):
    if resp.status_code == 200:
        try:
            return resp.json()
        except Exception as e:
            st.error(f"{context}: Eroare la parsarea JSON — {e}")
            return None
    else:
        st.error(f"{context}: HTTP {resp.status_code} — {resp.text[:300]}")
        return None


@st.cache_data(show_spinner=False, ttl=300)
def fetch_vehicles(api_key: str) -> List[Dict[str, Any]]:
    """Fetch vehicle list from FM Track using API key."""
    if not api_key:
        return []
    s = get_session(api_key)
    url = f"{FM_API_BASE}/objects"
    resp = s.get(url)
    data = handle_response(resp, "Eroare Vehicule API")
    if isinstance(data, list):
        return data
    return data or []


def fetch_events(vehicle_id: str, from_dt_utc: datetime, to_dt_utc: datetime, stationary_under_min: int, user_id: str) -> List[Dict[str, Any]]:
    """Fetch events from local API using selected object id as vehicle_id, with x-user-id header."""
    params = {
        "vehicle_id": str(vehicle_id),
        "from": to_iso_z(from_dt_utc),
        "to": to_iso_z(to_dt_utc),
        "stationary_under": int(stationary_under_min),
    }
    url = f"{EVENTS_BASE}/events"
    headers = {"Accept": "application/json", "x-user-id": user_id}
    resp = requests.get(url, params=params, headers=headers)
    data = handle_response(resp, "Eroare Events API")
    if isinstance(data, list):
        return data
    return data or []

# ==========================================
# Vehicle list & selection (kept)
# ==========================================

vehicles_list: List[Dict[str, Any]] = fetch_vehicles(api_key) if api_key else []
vehicle_options = {v.get("id"): v.get("name", v.get("id")) for v in vehicles_list}
selected_vehicle = st.sidebar.selectbox(
    "Selectează vehicul",
    options=list(vehicle_options.keys()) if vehicle_options else [None],
    format_func=lambda x: vehicle_options.get(x, "Fără vehicul") if x else "Nu există vehicule",
)

# ==========================================
# Data shaping helpers (testable) — comments in English
# ==========================================

def build_rows(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Transform raw events into table rows (Romanian headers)."""
    rows: List[Dict[str, Any]] = []
    for e in events:
        loc = e.get("location", {}) or {}
        raw_addr = (loc.get("address", {}) or {})
        addr = join_address(raw_addr)

        ev_type = (e.get("event_type") or "").upper()
        # If event is REFUEL or DRAIN, show fuel info in the Address cell
        if ev_type in {"REFUEL", "DRAIN"}:
            fls = e.get("fuel_level_start")
            fle = e.get("fuel_level_end")
            fld = e.get("fuel_difference")
            addr = f"{fls} | {fle} | {fld}"

        row = {
            "Tip eveniment": e.get("event_type"),
            "Start": fmt_dt_local(e.get("event_start")),
            "Sfârșit": fmt_dt_local(e.get("event_end")),
            "Durată": str(timedelta(seconds=int(e.get("duration_sec", 0)))) if e.get("duration_sec") is not None else None,
            "Lat": loc.get("latitude"),
            "Lon": loc.get("longitude"),
            "Adresă": addr,
            # mileage comes in meters → convert to km with 3 decimals (robust to None)
            "Kilometraj (pas) [km]": safe_km(e.get("mileage")),
            "Nivel combustibil": e.get("fuel_level"),
            "ID șofer": (e.get("driver_ids") or [None])[0],
            "ID brut": e.get("id"),
        }
        rows.append(row)
    return rows


def sort_and_cumulate(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by Start datetime, compute cumulative mileage column INCLUDING current row."""
    def _sort_key(val: Optional[str]):
        try:
            return parse_iso(val) or datetime.min.replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    if not df.empty:
        # rendezés idő szerint
        df.sort_values(by=["Start"], key=lambda s: s.map(_sort_key), inplace=True)
        # lépésoszlop -> numerikus
        step_series = pd.to_numeric(df["Kilometraj (pas) [km]"], errors="coerce").fillna(0)

        # kumulálás, de az első értéket kihagyva
        cumulative = step_series.cumsum().shift(fill_value=0)

        df["Kilometraj (cumulativ) [km]"] = cumulative
        df.drop(columns=["Kilometraj (pas) [km]"], inplace=True)
    return df


# ==========================================
# RUN — Fetch events and display table
# ==========================================

st.subheader("Evenimente")
run_clicked = st.button("RULEAZĂ", type="primary")

if run_clicked:
    if not selected_vehicle:
        st.warning("Selectează un vehicul pentru a rula.")
        st.stop()

    # Build UTC bounds from local dates (00:00 to 23:59:00 local)
    start_local = datetime.combine(from_date, datetime.min.time()).replace(tzinfo=display_tz)
    end_local = datetime.combine(to_date, datetime.max.time().replace(hour=23, minute=59, second=0, microsecond=0)).replace(tzinfo=display_tz)

    from_utc = start_local.astimezone(timezone.utc)
    to_utc = end_local.astimezone(timezone.utc)

    # Build API URL preview string
    preview_url = f"{EVENTS_BASE}/events?vehicle_id={selected_vehicle}&from={to_iso_z(from_utc)}&to={to_iso_z(to_utc)}&stationary_under={stationary_under}"
    st.markdown(f"**API Call:** `{preview_url}`")

    with st.spinner("Se încarcă evenimentele..."):
        events = fetch_events(str(selected_vehicle), from_utc, to_utc, stationary_under, user_id)

    if not events:
        st.info("Nu există evenimente în intervalul selectat.")
        st.stop()

    # Build table rows & dataframe (properly indented inside the click block)
    rows = build_rows(events)
    df = pd.DataFrame(rows)
    df = sort_and_cumulate(df)

    # Display table — use new Streamlit width API (no deprecation warning)
    st.dataframe(df, height=800, width="stretch")

    # Summary footer
    total_events = len(df)
    # Sum durations by parsing HH:MM:SS strings
    total_seconds = 0
    for v in df["Durată"].dropna():
        try:
            h, m, s = str(v).split(":")
            total_seconds += int(h) * 3600 + int(m) * 60 + int(s)
        except Exception:
            pass

    final_km = f"{df['Kilometraj (cumulativ) [km]'].iloc[-1]:.3f}" if not df.empty else "0.000"
    st.caption(f"Evenimente: {total_events} · Timp total: {timedelta(seconds=total_seconds)} · Kilometraj cumulativ final: {final_km} km")

    # ==============================
    # Map — show points with tooltips
    # ==============================
    try:
        import pydeck as pdk

        # Filter rows with valid coordinates
        df_map = df.copy()
        df_map = df_map[pd.notnull(df_map["Lat"]) & pd.notnull(df_map["Lon"])]
        df_map = df_map.astype({"Lat": float, "Lon": float})

        if not df_map.empty:
            # Pre-build tooltip HTML containing all row data
            df_map = df_map.copy()
            df_map["Tooltip"] = df_map.apply(build_tooltip_html, axis=1)

            # Compute a reasonable initial view (centered on mean lat/lon)
            center_lat = float(df_map["Lat"].mean())
            center_lon = float(df_map["Lon"].mean())

            # ScatterplotLayer markers
            layer = pdk.Layer(
                "ScatterplotLayer",
                data=df_map,
                get_position="[Lon, Lat]",
                get_radius=40,              # small marker (~40m)
                radius_min_pixels=3,        # ensure visibility when zoomed out
                radius_max_pixels=6,
                get_fill_color=[200, 30, 0, 160],
                get_line_color=[255, 255, 255],
                line_width_min_pixels=1,
                pickable=True,
            )

            tooltip = {
                "html": "{Tooltip}",
                "style": {"backgroundColor": "#ffffff", "color": "#111", "fontSize": "12px"},
            }

            deck = pdk.Deck(
                layers=[layer],
                initial_view_state=pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=9, pitch=0),
                map_style="light",
                tooltip=tooltip,
            )

            st.subheader("Hartă")
            st.pydeck_chart(deck)
        else:
            st.info("Nu există coordonate valide pentru afișarea pe hartă.")
    except Exception as e:
        st.warning(f"Nu s-a putut încărca harta: {e}")

# ==========================================
# Internal tests (optional) — run from the sidebar
# ==========================================

def _run_internal_tests():
    """Basic assertions to validate key helpers and shaping logic."""
    # safe_km
    assert safe_km(None) == 0.0
    assert safe_km("1000") == 1.0
    assert safe_km(1234) == 1.234

    # join_address
    assert join_address({"street": "Str", "house_number": "10", "locality": "Cluj", "country": "RO"}) == "Str, 10, Cluj, RO"
    assert join_address(None) == ""

    # build_rows with REFUEL formatting
    sample_events = [
        {
            "event_type": "REFUEL",
            "event_start": "2025-09-29T07:30:24.000Z",
            "event_end": "2025-09-29T07:30:24.000Z",
            "duration_sec": None,
            "fuel_level_start": 386.93,
            "fuel_level_end": 418.52,
            "fuel_difference": 31.59,
            "mileage": None,
            "location": {"latitude": 48.6, "longitude": 21.2, "address": None},
            "driver_ids": [],
            "id": 16,
        },
        {
            "event_type": "STOP",
            "event_start": "2025-09-29T07:03:18.000Z",
            "event_end": "2025-09-29T07:04:39.000Z",
            "duration_sec": 81,
            "mileage": 3326,
            "location": {"latitude": 47.1, "longitude": 21.87, "address": {"locality": "Oradea", "country": "Romania"}},
            "driver_ids": [],
            "id": 1462,
        },
    ]

    rows = build_rows(sample_events)
    # REFUEL/DRAIN must place fuel info into Adresă
    assert rows[0]["Adresă"] == "386.93 | 418.52 | 31.59"
    # Mileage step (km) for None is 0.0, for 3326 m is 3.326
    assert rows[0]["Kilometraj (pas) [km]"] == 0.0
    assert abs(rows[1]["Kilometraj (pas) [km]"] - 3.326) < 1e-6

    df = sort_and_cumulate(pd.DataFrame(rows))
    # Cumulative starts at 0.0 then adds subsequent steps
    assert "Kilometraj (cumulativ) [km]" in df.columns

    # Additional test: DRAIN formatting and tooltip building
    sample_events.append({
        "event_type": "DRAIN",
        "event_start": "2025-09-29T08:00:00.000Z",
        "event_end": "2025-09-29T08:05:00.000Z",
        "duration_sec": 300,
        "fuel_level_start": 200,
        "fuel_level_end": 150,
        "fuel_difference": -50,
        "mileage": 500,
        "location": {"latitude": 46.0, "longitude": 22.0, "address": {"locality": "Arad", "country": "Romania"}},
        "driver_ids": [],
        "id": 999,
    })
    rows2 = build_rows(sample_events)
    assert rows2[2]["Adresă"] == "200 | 150 | -50"
    # Tooltip string contains keys
    df2 = sort_and_cumulate(pd.DataFrame(rows2))
    tip_html = build_tooltip_html(df2.iloc[0])
    assert "Tip eveniment" in tip_html and "Adresă" in tip_html

    return "Toate testele au trecut."

run_tests = st.sidebar.checkbox("Rulează testele interne")
if run_tests:
    try:
        msg = _run_internal_tests()
        st.sidebar.success(msg)
    except AssertionError as e:
        st.sidebar.error(f"Test eșuat: {e}")
    except Exception as e:
        st.sidebar.error(f"Eroare în timpul testelor: {e}")
