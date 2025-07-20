#!/usr/bin/env python3

import json
import time
import threading
import sys
import re
import requests
from datetime import datetime, timezone, timedelta

import websocket
from bs4 import BeautifulSoup

from ticker_tracker import TickerTracker

from config import (
    UPCOMING_TOKENS_URL,
    REFRESH_INTERVAL,
    FLUCTUATION_CHECK_INTERVAL,
    FLUCTUATION_THRESHOLD,
    MAX_FLUCTUATION_WINDOW,
)

def fetch_upcoming_currencies(upcoming_page_url):
    response = requests.get(upcoming_page_url)
    response.raise_for_status()
    parsed_html = BeautifulSoup(response.text, "html.parser")

    upcoming = {}
    for upcoming_html_row in parsed_html.select("tbody tr"):
        name_tag = upcoming_html_row.select_one("span[label]")
        date_tag = upcoming_html_row.select_one("td + td span")
        if not (name_tag and date_tag):
            continue
        match = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", date_tag.text)
        if not match:
            continue
        upcoming[name_tag.text.strip().upper()] = datetime.strptime(match.group(0), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

    return upcoming

def should_refresh(last_refresh, now):
    return (now - last_refresh).total_seconds() >= REFRESH_INTERVAL

def refresh_upcoming(upcoming, processed, last_refresh, now):
    try:
        updated_upcoming_currencies = fetch_upcoming_currencies(UPCOMING_TOKENS_URL)
        for currencie, launch_date in updated_upcoming_currencies.items():
            if currencie not in upcoming:
                print(f"[{now.isoformat()}] + New upcoming: {currencie} at {launch_date.isoformat()}")
            elif upcoming[currencie] != launch_date and currencie not in processed:
                print(f"[{now.isoformat()}] → Updated launch: {currencie} at {launch_date.isoformat()}")
            upcoming[currencie] = launch_date
        return now
    except Exception as e:
        print(f"[{now.isoformat()}] ERROR fetching upcoming: {e}", file=sys.stderr)
        return last_refresh

def check_for_launch(upcoming, processed, now):
    for currencie, launch_date in upcoming.items():
        if currencie in processed:
            continue
        if now >= launch_date:
            threading.Thread(
                target=TickerTracker(currencie).start,
                daemon=True
            ).start()
            processed.add(currencie)

def tracker_loop():
    upcoming = {}
    processed = set()
    last_refresh = datetime.min.replace(tzinfo=timezone.utc)

    while True:
        now = datetime.now(timezone.utc)

        check_for_launch(upcoming, processed, now)

        if should_refresh(last_refresh, now):
            last_refresh = refresh_upcoming(upcoming, processed, last_refresh, now)

        time.sleep(FLUCTUATION_CHECK_INTERVAL)

def main():
    print("\n--- CURRENCIE TRACKER STARTED ---")
    print(f"- REFRESH_INTERVAL: {REFRESH_INTERVAL}s")
    print(f"- FLUCTUATION_THRESHOLD: {FLUCTUATION_THRESHOLD}% per second")
    print(f"- MAX_FLUCTUATION_WINDOW: {MAX_FLUCTUATION_WINDOW}s")
    print("---------------------------------\n")

    try:
        tracker_loop()
    except KeyboardInterrupt:
        print("\nExecution interrupted by user")
        sys.exit(0)

if __name__ == "__main__":
    main()
