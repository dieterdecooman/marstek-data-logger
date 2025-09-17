import streamlit as st
import pandas as pd
from influxdb_client import InfluxDBClient
from bokeh.plotting import figure
from bokeh.models import ColumnDataSource, HoverTool
from bokeh.palettes import Category10
from streamlit_bokeh import st_bokeh
import pytz
from datetime import datetime, timedelta

# --- InfluxDB settings ---
INFLUX_URL = st.secrets["influx_url"]
INFLUX_TOKEN = st.secrets["influx_token"]
INFLUX_ORG = st.secrets["influx_org"]
INFLUX_BUCKET = st.secrets["influx_bucket"]

tz_brussels = pytz.timezone("Europe/Brussels")

# --- Query function ---
@st.cache_data
def query_influx(day: datetime):
    start = day.astimezone(pytz.UTC)
    end = (day + timedelta(days=1)).astimezone(pytz.UTC)
    flux = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: {start.isoformat()}, stop: {end.isoformat()})
      |> filter(fn: (r) => r._measurement == "battery" and r._field == "soc")
      |> keep(columns: ["_time", "_value", "device_id"])
      |> sort(columns: ["_time"])
      |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
    '''
    with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
        query_api = client.query_api()
        df = query_api.query_data_frame(flux)
        if "_time" in df.columns:
            df["_time"] = pd.to_datetime(df["_time"]).dt.tz_convert(tz_brussels)
        return df

# --- Sidebar ---
day_selected = st.date_input("Select day", datetime.now(tz_brussels))
df = query_influx(day_selected)

if df.empty:
    st.info("No data for selected day")
else:
    # --- Prepare Bokeh figure ---
    p = figure(x_axis_type="datetime", height=400, sizing_mode="stretch_width", title="Battery SOC")
    palette = Category10[10]
    devices = df["device_id"].unique()
    for i, device in enumerate(devices):
        df_device = df[df["device_id"] == device]
        source = ColumnDataSource(df_device)
        p.line("_time", "_value", source=source, color=palette[i % 10], legend_label=device, line_width=2)
        p.circle("_time", "_value", source=source, color=palette[i % 10], size=5)
    p.legend.location = "bottom_left"
    p.add_tools(HoverTool(tooltips=[("Time", "@_time{%F %H:%M}"), ("SOC", "@_value")],
                          formatters={"@_time": "datetime"}))

    st_bokeh(p)
