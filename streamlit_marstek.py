import streamlit as st
import pandas as pd
import plotly.express as px
from influxdb_client import InfluxDBClient
from influxdb_client.client.query_api import QueryApi
from pytz import timezone
from datetime import datetime

# --- InfluxDB connection ---
INFLUX_URL = "http://localhost:8086"  # Replace with your Influx URL
INFLUX_TOKEN = "your_token_here"
INFLUX_ORG = "your_org_here"
INFLUX_BUCKET = "your_bucket_here"

client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
query_api = client.query_api()

# --- Query data ---
query = f'''
from(bucket:"{INFLUX_BUCKET}")
  |> range(start: -30d)  // last 30 days
  |> filter(fn: (r) => r["_measurement"] == "soc") 
  |> filter(fn: (r) => r["_field"] == "value")
  |> keep(columns: ["_time", "_value"])
'''

tables = query_api.query(query)
records = []

for table in tables:
    for record in table.records:
        records.append((record.get_time(), record.get_value()))

# Convert to DataFrame
data = pd.DataFrame(records, columns=["timestamp", "SOC"])

# Convert to Brussels timezone
brussels_tz = timezone('Europe/Brussels')
data['timestamp'] = data['timestamp'].dt.tz_convert(brussels_tz)
data['date'] = data['timestamp'].dt.date

# --- Streamlit UI ---
st.title("SOC Dashboard - Brussels Time")

# Default date = today in Brussels
today_brussels = datetime.now(brussels_tz).date()
selected_day = st.date_input("Select a day", value=today_brussels, min_value=data['date'].min(), max_value=data['date'].max())

# Filter data
filtered_data = data[data['date'] == selected_day]

# Show graph
if not filtered_data.empty:
    fig = px.line(filtered_data, x='timestamp', y='SOC', 
                  title=f"SOC on {selected_day} (Brussels Time)",
                  labels={'timestamp': 'Time', 'SOC': 'State of Charge (%)'})
    st.plotly_chart(fig)
else:
    st.write("No data available for this day.")
