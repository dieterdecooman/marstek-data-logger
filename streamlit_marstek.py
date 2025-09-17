import streamlit as st
import pandas as pd
import plotly.express as px
from influxdb_client import InfluxDBClient
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# -------------------
# Streamlit app: Battery SOC viewer (InfluxDB v2)
# - Select a date (calendar or dropdown)
# - Queries InfluxDB for measurement "battery" field "soc"
# - Converts UTC times from Influx to Europe/Brussels for display
# - Uses Plotly with smooth (spline) lines for nicer visuals
# -------------------

st.set_page_config(page_title="Battery SOC — Influx viewer", layout="wide")
st.title("Battery SOC — InfluxDB Viewer")

# --- Read Influx credentials from Streamlit secrets ---
# Put the following in your app's Secrets (share.streamlit.io -> Settings -> Secrets):
# INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET
INFLUX_URL = st.secrets.get("INFLUX_URL")
INFLUX_TOKEN = st.secrets.get("INFLUX_TOKEN")
INFLUX_ORG = st.secrets.get("INFLUX_ORG")
INFLUX_BUCKET = st.secrets.get("INFLUX_BUCKET")

if not (INFLUX_URL and INFLUX_TOKEN and INFLUX_ORG and INFLUX_BUCKET):
    st.error("Missing InfluxDB credentials in Streamlit secrets. Add INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG and INFLUX_BUCKET.")
    st.stop()

# timezone handling
LOCAL_TZ = ZoneInfo("Europe/Brussels")
UTC = timezone.utc

# --- Utility: build Flux query for a given UTC start/stop ---
def build_flux_query(bucket: str, start_iso_utc: str, stop_iso_utc: str) -> str:
    # Query only the 'soc' field of measurement 'battery'
    # keep device_id / name for grouping
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: {start_iso_utc}, stop: {stop_iso_utc})
  |> filter(fn: (r) => r._measurement == "battery" and r._field == "soc")
  |> keep(columns: ["_time", "_value", "device_id", "name"])
  |> sort(columns: ["_time"])'''
    return flux

# --- Cached query function ---
@st.cache_data(ttl=60)
def query_influx(start_iso_utc: str, stop_iso_utc: str) -> pd.DataFrame:
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    query_api = client.query_api()
    flux = build_flux_query(INFLUX_BUCKET, start_iso_utc, stop_iso_utc)

    # query_data_frame returns a DataFrame when possible; may return multiple frames
    try:
        df = query_api.query_data_frame(flux)
    finally:
        client.close()

    # If result is empty or not a dataframe
    if df is None or df.empty:
        return pd.DataFrame()

    # query_data_frame may return an aggregated dataframe with additional metadata rows
    # Keep only rows that contain '_time' and '_value'
    if "_time" not in df.columns or "_value" not in df.columns:
        # Sometimes the returned df is a list of frames — try to concatenate
        try:
            df_all = pd.concat(df)
            df = df_all
        except Exception:
            return pd.DataFrame()

    df = df.reset_index(drop=True)

    # ensure types
    df["_time"] = pd.to_datetime(df["_time"]).dt.tz_convert("UTC")
    df = df[["_time", "_value", "device_id", "name"]]
    df.rename(columns={"_time": "time_utc", "_value": "soc"}, inplace=True)
    return df

# --- UI: date selection ---
with st.sidebar:
    st.header("Select day to view")

    # default to today in Brussels
    today_local = datetime.now(LOCAL_TZ).date()
    selected_date = st.date_input("Choose date", value=today_local)

    # quick dropdown of last 7 days
    last_days = [(today_local - timedelta(days=i)) for i in range(0, 14)]
    last_days_str = [d.isoformat() for d in last_days]
    chosen_quick = st.selectbox("Quick select recent day", options=last_days_str, index=0)

    if chosen_quick:
        try:
            # replace selected_date with quick selection if different
            if chosen_quick != selected_date.isoformat():
                selected_date = datetime.fromisoformat(chosen_quick).date()
        except Exception:
            pass

    sampling = st.selectbox("Sampling", ["raw", "resample:1min", "resample:5min"], index=1)

    st.markdown("---")
    st.write("Timezone: **Europe/Brussels** (display). Influx stores timestamps in UTC.")
    if st.button("Refresh now"):
        # clear cache for next query
        st.cache_data.clear()

# compute start/end in local tz and convert to UTC ISO
start_local = datetime.combine(selected_date, time(0, 0, 0), tzinfo=LOCAL_TZ)
# include full day until next day midnight (exclusive)
end_local = datetime.combine(selected_date + timedelta(days=1), time(0, 0, 0), tzinfo=LOCAL_TZ)

start_utc = start_local.astimezone(UTC)
end_utc = end_local.astimezone(UTC)

# Flux accepts RFC3339 timestamps; wrap in quotes in the flux builder
start_iso = start_utc.isoformat()
end_iso = end_utc.isoformat()

st.subheader(f"SOC for {selected_date.isoformat()} (local: Europe/Brussels)")
st.write(f"Querying InfluxDB bucket: `{INFLUX_BUCKET}` from **{start_utc.isoformat()} UTC** to **{end_utc.isoformat()} UTC**")

# Query
with st.spinner("Querying InfluxDB..."):
    df = query_influx(start_iso, end_iso)

if df.empty:
    st.info("No data for selected day")
    st.stop()

# convert UTC times to local tz for display
df["time_local"] = pd.to_datetime(df["time_utc"]).dt.tz_convert("Europe/Brussels")

# optional resampling / downsampling
if sampling.startswith("resample"):
    try:
        freq = "1T" if "1min" in sampling else "5T"
        # We group by device and resample
        df.set_index("time_local", inplace=True)
        agg = df.groupby("device_id").resample(freq)["soc"].mean().dropna()
        agg = agg.reset_index()
        plot_df = agg
    except Exception:
        plot_df = df.reset_index(drop=True)
else:
    plot_df = df.reset_index(drop=True)

# Plot with plotly for smooth curves
fig = px.line(
    plot_df,
    x="time_local",
    y="soc",
    color="device_id",
    labels={"time_local": "Time (Europe/Brussels)", "soc": "State of Charge (%)", "device_id": "Device"},
    title=f"Battery SOC on {selected_date.isoformat()}",
    line_shape="spline",
)

fig.update_layout(transition_duration=300)
fig.update_traces(mode="lines+markers", marker=dict(size=4))
fig.update_yaxes(range=[0, 100])

st.plotly_chart(fig, use_container_width=True)

# show raw data toggle
with st.expander("Show raw data"):
    st.dataframe(plot_df.sort_values("time_local").reset_index(drop=True))

# footer
st.caption("Timestamps shown in Europe/Brussels. Data queried from InfluxDB (UTC) and converted client-side.")
