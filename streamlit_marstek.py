import streamlit as st
import pandas as pd
from influxdb_client import InfluxDBClient
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import warnings

# Bokeh imports
from bokeh.plotting import figure
from bokeh.models import ColumnDataSource, HoverTool, DatetimeTickFormatter, Legend
from bokeh.palettes import Category10, Category20
import math

# -------------------
# Streamlit app: Battery SOC viewer (InfluxDB v2) using Bokeh
# - Select a date (calendar or dropdown)
# - Queries InfluxDB for measurement "battery" field "soc"
# - Converts UTC times from Influx to Europe/Brussels for display
# - Uses Bokeh for a mobile-friendly chart with toolbar and legend BELOW the chart
# -------------------

st.set_page_config(page_title="Battery SOC — Influx viewer (Bokeh)", layout="wide")
st.title("Battery SOC — InfluxDB Viewer (Bokeh)")

# --- Read Influx credentials from Streamlit secrets ---
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

# suppress pivot warning (we use pivot in query)
from influxdb_client.client.warnings import MissingPivotFunction
warnings.simplefilter("ignore", MissingPivotFunction)

# --- Flux query builder with pivot ---
def build_flux_query_with_pivot(bucket: str, start_iso_utc: str, stop_iso_utc: str) -> str:
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: {start_iso_utc}, stop: {stop_iso_utc})
  |> filter(fn: (r) => r._measurement == "battery" and r._field == "soc")
  |> keep(columns: ["_time", "_value", "device_id", "name", "_field"])
  |> pivot(rowKey:["_time","device_id","name"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
'''
    return flux

# --- Cached query function ---
@st.cache_data(ttl=60)
def query_influx(start_iso_utc: str, stop_iso_utc: str) -> pd.DataFrame:
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    query_api = client.query_api()
    flux = build_flux_query_with_pivot(INFLUX_BUCKET, start_iso_utc, stop_iso_utc)

    try:
        df = query_api.query_data_frame(flux)
    finally:
        client.close()

    # handle different return shapes
    if df is None:
        return pd.DataFrame()

    # sometimes query_data_frame returns a list of frames
    if isinstance(df, list):
        try:
            df = pd.concat(df, ignore_index=True)
        except Exception:
            return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    # After pivot, sos should be in column 'soc' or '_value'
    # Normalize columns
    if "_time" in df.columns:
        df = df.rename(columns={"_time": "time_utc"})
    if "soc" not in df.columns and "_value" in df.columns:
        df = df.rename(columns={"_value": "soc"})

    # Keep only useful columns
    cols = [c for c in ["time_utc", "device_id", "name", "soc"] if c in df.columns]
    df = df[cols].copy()

    # Ensure timezone-aware UTC
    df["time_utc"] = pd.to_datetime(df["time_utc"]) 
    if df["time_utc"].dt.tz is None:
        df["time_utc"] = df["time_utc"].dt.tz_localize("UTC")
    else:
        df["time_utc"] = df["time_utc"].dt.tz_convert("UTC")

    return df

# --- UI: date selection ---
with st.sidebar:
    st.header("Select day to view")

    # default to today in Brussels
    today_local = datetime.now(LOCAL_TZ).date()
    selected_date = st.date_input("Choose date", value=today_local)

    # quick dropdown of last 14 days
    last_days = [(today_local - timedelta(days=i)) for i in range(0, 14)]
    last_days_str = [d.isoformat() for d in last_days]
    chosen_quick = st.selectbox("Quick select recent day", options=last_days_str, index=0)

    if chosen_quick:
        try:
            if chosen_quick != selected_date.isoformat():
                selected_date = datetime.fromisoformat(chosen_quick).date()
        except Exception:
            pass

    sampling = st.selectbox("Sampling", ["raw", "resample:1min", "resample:5min"], index=1)

    st.markdown("---")
    st.write("Timezone: **Europe/Brussels** (display). Influx stores timestamps in UTC.")
    if st.button("Refresh now"):
        st.cache_data.clear()

# compute start/end in local tz and convert to UTC ISO
start_local = datetime.combine(selected_date, time(0, 0, 0), tzinfo=LOCAL_TZ)
end_local = datetime.combine(selected_date + timedelta(days=1), time(0, 0, 0), tzinfo=LOCAL_TZ)

start_utc = start_local.astimezone(UTC)
end_utc = end_local.astimezone(UTC)

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
df["time_local"] = df["time_utc"].dt.tz_convert("Europe/Brussels")

# optional resampling / downsampling
if sampling.startswith("resample"):
    try:
        freq = "1T" if "1min" in sampling else "5T"
        df.set_index("time_local", inplace=True)
        agg = df.groupby("device_id").resample(freq)["soc"].mean().dropna()
        agg = agg.reset_index()
        plot_df = agg
    except Exception:
        plot_df = df.reset_index(drop=True)
else:
    plot_df = df.reset_index(drop=True)

# Ensure we have required columns
if "time_local" not in plot_df.columns or "soc" not in plot_df.columns:
    st.error("Data frame missing required columns for plotting")
    st.stop()

# --- Bokeh plotting function ---
def plot_bokeh_soc(plot_df: pd.DataFrame):
    df = plot_df.copy()

    # Prepare x values as naive datetimes representing local wall time
    # Bokeh will render them; keep a string for hover
    df["time_local_naive"] = df["time_local"].dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    df["time_str_local"] = df["time_local"].dt.strftime('%Y-%m-%d %H:%M:%S')

    devices = df["device_id"].astype(str).unique().tolist()
    n = len(devices)
    if n <= 10:
        palette = Category10[max(3, n)]
    else:
        palette = Category20[min(20, n)]

    p = figure(
        x_axis_type="datetime",
        sizing_mode="stretch_width",
        height=380,
        toolbar_location="below",
        tools="pan,wheel_zoom,box_zoom,reset,save",
        active_drag="pan",
    )

    p.xaxis.formatter = DatetimeTickFormatter(
    hours="%H:%M",
    days="%d %b",
    months="%b %Y",
    years="%Y"
    )
    p.xaxis.major_label_orientation = math.pi / 4
    p.yaxis.axis_label = "State of Charge (%)"
    p.y_range.start = 0
    p.y_range.end = 100
    p.grid.grid_line_alpha = 0.25

    hover = HoverTool(
        tooltips=[
            ("Time (local)", "@time_str_local"),
            ("Device", "@device_id"),
            ("SOC", "@soc{0.0}%"),
        ],
        mode="vline",
    )
    p.add_tools(hover)

    legend_items = []
    for i, dev in enumerate(devices):
        dev_df = df[df["device_id"].astype(str) == str(dev)].sort_values("time_local_naive")
        if dev_df.empty:
            continue
        source = ColumnDataSource(data={
            "x": dev_df["time_local_naive"],
            "soc": dev_df["soc"],
            "time_str_local": dev_df["time_str_local"],
            "device_id": dev_df["device_id"].astype(str),
        })
        color = palette[i % len(palette)]
        r = p.line(x="x", y="soc", source=source, line_width=2.5, color=color, alpha=0.9)
        p.circle(x="x", y="soc", source=source, size=4, color=color, alpha=0.9)
        legend_items.append((str(dev), [r]))

    if legend_items:
        legend = Legend(items=legend_items, location="center")
        legend.click_policy = "hide"
        p.add_layout(legend, 'below')

    return p

# Render the plot
p = plot_bokeh_soc(plot_df)
st.bokeh_chart(p, use_container_width=True)

with st.expander("Show raw data"):
    st.dataframe(plot_df.sort_values("time_local").reset_index(drop=True))

st.caption("Timestamps shown in Europe/Brussels. Data queried from InfluxDB (UTC) and converted client-side.")
