name: Log battery SOC to InfluxDB

on:
  schedule:
    - cron: '*/5 * * * *'   # every 5 minutes (UTC)
  workflow_dispatch: {}       # allows manual trigger from Actions UI

permissions:
  contents: read  # no write needed, we don't commit files

jobs:
  poll-and-write:
    runs-on: ubuntu-latest
    steps:
      # 1. Checkout repo
      - name: Checkout repo
        uses: actions/checkout@v4

      # 2. Setup Python
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      # 3. Cache pip packages
      - name: Cache pip
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements.txt') }}
          restore-keys: |
            ${{ runner.os }}-pip-

      # 4. Install dependencies
      - name: Install requirements
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      # 5. Run the logger
      - name: Run logger and write to InfluxDB
        env:
          HAME_EMAIL: ${{ secrets.HAME_EMAIL }}
          HAME_MD5_PASSWORD: ${{ secrets.HAME_MD5_PASSWORD }}
          HAME_PASSWORD: ${{ secrets.HAME_PASSWORD }}
          INFLUX_URL: ${{ secrets.INFLUX_URL }}
          INFLUX_TOKEN: ${{ secrets.INFLUX_TOKEN }}
          INFLUX_ORG: ${{ secrets.INFLUX_ORG }}
          INFLUX_BUCKET: ${{ secrets.INFLUX_BUCKET }}
        run: |
          python log_to_influx.py
