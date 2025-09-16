#!/usr/bin/env python3
# log_to_influx.py
"""
Poll HameData once and write device metrics to InfluxDB v2.
Designed for scheduled GitHub Actions runs.
"""

import os
import hashlib
import requests
from datetime import datetime, timezone
from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS

# HameData endpoints
LOGIN_URL = "https://eu.hamedata.com/app/Solar/v2_get_device.php"
GET_DEVICES_URL = "https://eu.hamedata.com/ems/api/v1/getDeviceList"

# Read env / secrets (set by GitHub Actions)
HAME_EMAIL = os.environ.get("HAME_EMAIL")
HAME_MD5_PASSWORD = os.environ.get("HAME_MD5_PASSWORD")
HAME_PASSWORD = os.environ.get("HAME_PASSWORD")

INFLUX_URL = os.environ.get("INFLUX_URL")
INFLUX_TOKEN = os.environ.get("INFLUX_TOKEN")
INFLUX_ORG = os.environ.get("INFLUX_ORG")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET")

if not HAME_EMAIL:
    raise SystemExit("HAME_EMAIL not set")
if not (HAME_MD5_PASSWORD or HAME_PASSWORD):
    raise SystemExit("HAME_MD5_PASSWORD or HAME_PASSWORD not set")
if not (INFLUX_URL and INFLUX_TOKEN and INFLUX_ORG and INFLUX_BUCKET):
    raise SystemExit("InfluxDB credentials (INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET) not set")

def md5_of(text: str) -> str:
    import hashlib
    return hashlib.md5(text.encode("utf-8")).hexdigest()

def get_token(email: str, md5_pwd: str, timeout=15):
    params = {"pwd": md5_pwd, "mailbox": email}
    r = requests.post(LOGIN_URL, params=params, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    token = j.get("token")
    if not token:
        raise RuntimeError(f"Login did not return token: {j}")
    return token

def get_device_list(token: str, timeout=15):
    r = requests.get(GET_DEVICES_URL, params={"token": token}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def to_float_or_none(x):
    try:
        return float(x)
    except Exception:
        return None

def main():
    md5_pwd = HAME_MD5_PASSWORD if HAME_MD5_PASSWORD else md5_of(HAME_PASSWORD)
    token = get_token(HAME_EMAIL, md5_pwd)
    j = get_device_list(token)
    data = j.get("data") or []
    if not data:
        print("No device data; exiting")
        return

    # Initialize Influx client
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)  # synchronous write suited for small batches in actions

    points = []
    for entry in data:
        # Build a point. Measurement name: "battery"
        # Tags: device_id, name, mac, type (if present)
        # Fields: soc, charge, discharge, load, pv, profit (as float where possible)
        # Timestamp: use device report_time if available (epoch seconds), else now UTC
        tags = {
            "device_id": entry.get("devid", ""),
            "name": entry.get("name", "") or "",
            "mac": entry.get("mac", "") or "",
            "type": entry.get("type", "") or ""
        }

        # Choose timestamp
        ts_epoch = entry.get("report_time")
        if ts_epoch:
            try:
                ts = datetime.fromtimestamp(int(ts_epoch), tz=timezone.utc)
            except Exception:
                ts = datetime.now(timezone.utc)
        else:
            ts = datetime.now(timezone.utc)

        # Fields (type-converted)
        soc = to_float_or_none(entry.get("soc"))
        charge = to_float_or_none(entry.get("charge"))
        discharge = to_float_or_none(entry.get("discharge"))
        load = to_float_or_none(entry.get("load"))
        pv = to_float_or_none(entry.get("pv"))
        profit = None
        try:
            profit = float(str(entry.get("profit")).replace(",", "."))  # sometimes string "-0.56"
        except Exception:
            profit = None

        p = (
            Point("battery")
            .tag("device_id", tags["device_id"])
            .tag("name", tags["name"])
            .tag("mac", tags["mac"])
            .tag("type", tags["type"])
            .field("soc", soc if soc is not None else 0.0)
            .field("charge", charge if charge is not None else 0.0)
            .field("discharge", discharge if discharge is not None else 0.0)
            .field("load", load if load is not None else 0.0)
            .field("pv", pv if pv is not None else 0.0)
        )

        # optionally include profit if parsable
        if profit is not None:
            p = p.field("profit", profit)

        p = p.time(ts)
        points.append(p)

    if not points:
        print("No points to write")
        return

    # Write points
    write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=points)
    print(f"Wrote {len(points)} point(s) to InfluxDB bucket '{INFLUX_BUCKET}'")

    write_api.__del__()  # cleanup
    client.__del__()

if __name__ == "__main__":
    main()
