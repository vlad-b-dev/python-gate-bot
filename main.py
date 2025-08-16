#!/usr/bin/env python3

import argparse
import time
import threading
import sys
import os
import logging
from datetime import datetime, timezone
from ticker_tracker import TickerTracker

LOG_DIR = "C:/Users/usuario/python/python-gate-bot/logs"
os.makedirs(LOG_DIR, exist_ok=True) 

LOG_FILE = os.path.join(LOG_DIR, "gate-bot.log")  

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8")
    ]
)

def fetch_upcoming_currencies(upcoming_page_url):
    import requests
    import re
    from datetime import datetime, timezone
    from bs4 import BeautifulSoup

    response = requests.get(upcoming_page_url)
    response.raise_for_status()
    parsed_html = BeautifulSoup(response.text, "html.parser")

    upcoming = {}
    for row in parsed_html.select("tbody tr"):
        name_tag = row.select_one("span[label]")
        date_tag = row.select_one("td + td span")
        if not (name_tag and date_tag):
            continue
        match = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", date_tag.text)
        if not match:
            continue
        upcoming[name_tag.text.strip().upper()] = datetime.strptime(
            match.group(0),
            "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)

    return upcoming

def should_refresh(last_refresh, now, refresh_interval):
    return (now - last_refresh).total_seconds() >= refresh_interval

def refresh_upcoming(upcoming, processed, last_refresh, now, upcoming_tokens_url):
    try:
        updated = fetch_upcoming_currencies(upcoming_tokens_url)
        for sym, launch_date in updated.items():
            if sym not in upcoming:
                logging.info(f"+ New upcoming: {sym} at {launch_date.isoformat()}")

            elif upcoming[sym] != launch_date and sym not in processed:
                logging.info(f"→ Updated launch: {sym} at {launch_date.isoformat()}")
            upcoming[sym] = launch_date
        return now
    except Exception as e:
        logging.info(f"ERROR fetching upcoming: {e}")
        return last_refresh

def check_for_launch(upcoming, processed, now):
    for sym, launch_date in upcoming.items():
        if sym in processed:
            continue
        if now >= launch_date:
            threading.Thread(
                target=TickerTracker(sym).start,
                daemon=True
            ).start()
            processed.add(sym)

def tracker_loop(upcoming_tokens_url, refresh_interval, fluctuation_check_interval):
    upcoming = {}
    processed = set()
    last_refresh = datetime.min.replace(tzinfo=timezone.utc)

    while True:
        now = datetime.now(timezone.utc)
        check_for_launch(upcoming, processed, now)

        if should_refresh(last_refresh, now, refresh_interval):
            last_refresh = refresh_upcoming(
                upcoming, processed, last_refresh, now, upcoming_tokens_url
            )

        time.sleep(fluctuation_check_interval)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test", "-t",
        metavar="SYMBOL",
        help="immediately track SYMBOL (e.g. ESPORTS)"
    )
    args = parser.parse_args()

    if args.test:
        symbol = args.test.upper()
        logging.info(f"🚀 TEST MODE: launching tracker for {symbol}")
        threading.Thread(target=TickerTracker(symbol).start, daemon=True).start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nTest interrupted by user")
            sys.exit(0)

    import requests 
    import re
    from bs4 import BeautifulSoup
    from config import (
        UPCOMING_TOKENS_URL,
        REFRESH_INTERVAL,
        FLUCTUATION_CHECK_INTERVAL,
        FLUCTUATION_THRESHOLD,     
        MAX_FLUCTUATION_WINDOW,    
    )

    print("\n--- CURRENCIE TRACKER STARTED ---")
    print(f"- REFRESH_INTERVAL: {REFRESH_INTERVAL}s")
    print(f"- FLUCTUATION_THRESHOLD: {FLUCTUATION_THRESHOLD}% per second")
    print(f"- MAX_FLUCTUATION_WINDOW: {MAX_FLUCTUATION_WINDOW}s")
    print("---------------------------------\n")

    try:
        tracker_loop(
            UPCOMING_TOKENS_URL,
            REFRESH_INTERVAL,
            FLUCTUATION_CHECK_INTERVAL
        )
    except KeyboardInterrupt:
        print("\nExecution interrupted by user")
        sys.exit(0)

if __name__ == "__main__":
    main()
