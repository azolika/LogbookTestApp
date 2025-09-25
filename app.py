import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import math

st.title("Vehicle Trips with Geozones")

# --- Sidebar: API Key, Vehicle, Date range ---
api_key = st.sidebar.text_input("API Key", type="password")

from_date = st.sidebar.date_input("From")
to_date = st.sidebar.date_input("To")

# --- Fetch vehicles ---
vehicles_list = []
if api_key:
    try:
        vehicles_url = f"https://api.fm-track.com/objects?version=1&api_key={api_key}"
        vehicles_response = requests.get(vehicles_url)
        if vehicles_response.status_code == 200:
            vehicles_list = vehicles_response.json()
        else:
            st.sidebar.warning(f"Vehicles API error: {vehicles_response.status_code}")
    except Exception as e:
        st.sidebar.error(f"Error fetching vehicles: {e}")

vehicle_options = {v["id"]: v.get("name", v.get("id")) for v in vehicles_list}
selected_vehicle = st.sidebar.selectbox("Select Vehicle", options=list(vehicle_options.keys()),
                                        format_func=lambda x: vehicle_options[x])

# --- Fetch geozones ---
geozone_list = []
if api_key:
    try:
        geozones_url = f"https://api.fm-track.com/geozones?version=1&limit=1000&api_key={api_key}"
        geozones_response = requests.get(geozones_url)
        if geozones_response.status_code == 200:
            # Convert JSON text to Python list/dict
            geozone_list = geozones_response.json()  # <-- biztosítsuk, hogy ez tényleg lista
            if isinstance(geozone_list, dict) and "items" in geozone_list:
                # Ha a JSON "items" kulcs alatt van a lista
                geozone_list = geozone_list["items"]
        else:
            st.sidebar.warning(f"Geozones API error: {geozones_response.status_code}")
    except Exception as e:
        st.sidebar.error


# --- Filter POINT geozones ---
point_geozones = [g for g in geozone_list if g.get("type") == "POINT" and g.get("circle")]


# --- Haversine function ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# --- Vehicle Trips Section ---
st.subheader("Vehicle Trips")

if selected_vehicle and from_date and to_date:
    if st.button("RUN"):
        try:
            from_iso = from_date.strftime("%Y-%m-%dT00:00:00.000Z")
            to_iso = to_date.strftime("%Y-%m-%dT23:59:00.000Z")

            trips_url = (
                f"https://api.fm-track.com/objects/{selected_vehicle}/trips"
                f"?version=1&from_datetime={from_iso}&to_datetime={to_iso}&limit=1000&api_key={api_key}"
            )

            #st.markdown(f"**API Call:** `{trips_url}`")

            trips_response = requests.get(trips_url)
            if trips_response.status_code == 200:
                trips_data = trips_response.json()
                trips_list = trips_data.get("trips", [])

                if trips_list:
                    def format_duration(seconds):
                        return str(timedelta(seconds=seconds))


                    def format_datetime(dt_str):
                        try:
                            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                            return dt.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            return dt_str


                    table_rows = []
                    for t in trips_list:
                        start = t["trip_start"]
                        end = t["trip_end"]
                        start_lat = start.get("latitude")
                        start_lon = start.get("longitude")
                        end_lat = end.get("latitude")
                        end_lon = end.get("longitude")

                        start_address = ", ".join(
                            filter(None, [
                                start["address"].get("street"),
                                start["address"].get("house_number"),
                                start["address"].get("locality"),
                                start["address"].get("region"),
                                start["address"].get("country")
                            ])
                        )
                        end_address = ", ".join(
                            filter(None, [
                                end["address"].get("street"),
                                end["address"].get("house_number"),
                                end["address"].get("locality"),
                                end["address"].get("region"),
                                end["address"].get("country")
                            ])
                        )
                        driver_id = t["driver_ids"][0] if t.get("driver_ids") else None

                        # --- Find geozones containing start and end points ---
                        start_geozones = []
                        end_geozones = []
                        for g in point_geozones:
                            glat = g["circle"]["latitude"]
                            glon = g["circle"]["longitude"]
                            radius = g["circle"]["radius"]
                            if start_lat is not None and start_lon is not None:
                                if haversine(start_lat, start_lon, glat, glon) <= radius:
                                    start_geozones.append(g.get("name"))
                            if end_lat is not None and end_lon is not None:
                                if haversine(end_lat, end_lon, glat, glon) <= radius:
                                    end_geozones.append(g.get("name"))

                        row = {
                            "Start Datetime": format_datetime(start.get("datetime")),
                            "Start Address": start_address,
                            "Start Latitude": start_lat,
                            "Start Longitude": start_lon,
                            "Start Geozones": ", ".join(start_geozones),
                            "End Datetime": format_datetime(end.get("datetime")),
                            "End Address": end_address,
                            "End Latitude": end_lat,
                            "End Longitude": end_lon,
                            "End Geozones": ", ".join(end_geozones),
                            "Mileage (km)": round(t.get("mileage", 0) / 1000, 3),
                            "Fuel Consumed": t.get("total_fuel_consumption"),
                            "Trip Duration": format_duration(t.get("trip_duration", 0)),
                            "Driver ID": driver_id
                        }
                        table_rows.append(row)

                    df = pd.DataFrame(table_rows)
                    st.dataframe(df)

                else:
                    st.warning("No trips found for this vehicle in the selected period.")
            else:
                st.error(f"Trips API error: {trips_response.status_code} - {trips_response.text}")
        except Exception as e:
            st.error(f"Error fetching trips: {e}")
