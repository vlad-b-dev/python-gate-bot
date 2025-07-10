#!/usr/bin/env python3

import time
import threading
import sys
import re
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from config import (
    UPCOMING_TOKENS_URL,
    TICKER_URL,
    REFRESH_INTERVAL,
    FLUCTUATION_CHECK_INTERVAL,
    FLUCTUATION_THRESHOLD,
    MAX_FLUCTUATION_WINDOW,
)


def fetch_upcoming_currencies(upcoming_page_url):
    response = requests.get(upcoming_page_url)
    response.raise_for_status()
    parsed_html = BeautifulSoup(response.text, "html.parser")

    upcoming_currencies = {}
    for row in parsed_html.select("tbody tr"):
        name_tag = row.select_one("span[label]")
        date_tag = row.select_one("td + td span")
        if not (name_tag and date_tag):
            continue
        date_match = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", date_tag.text)
        if not date_match:
            continue
        upcoming_currencies[name_tag.text.strip().upper()] = datetime.strptime(date_match.group(0), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

    return upcoming_currencies



def check_currencie_at_launch(currencie: str):
    initial_time = datetime.now(timezone.utc)
    try:
        initial_request = requests.get(TICKER_URL.format(currencie))
        initial_request.raise_for_status()
        initial_price = float(initial_request.json()['last'])
    except Exception as e:
        print(f"[{initial_time.isoformat()}] ERROR fetching {currencie} at launch: {e}", file=sys.stderr)
        return

    print(f"[{initial_time.isoformat()}] ✅ Socket connected for {currency} — initial price: {initial_price:.8f} USDT")

    while True:
        time.sleep(1)
        now = datetime.now(timezone.utc)
        elapsed = (now - initial_time).total_seconds()

        if elapsed > MAX_FLUCTUATION_WINDOW:
            break
        try:
            current_request = requests.get(TICKER_URL.format(currencie))
            current_request.raise_for_status()
            current_price = float(current_request.json()['last'])
        except Exception as e:
            print(f"[{now.isoformat()}] ERROR fetching {currencie} (observe): {e}", file=sys.stderr)
            continue
        
        speed = ((current_price - initial_price) / initial_price * 100) / elapsed if elapsed else 0.0

        if abs(speed) > FLUCTUATION_THRESHOLD:
            print(
                f"[{now.isoformat()}] ⚠️ {currencie} speed {speed:+.2f}%/s "
                f"over {int(elapsed)}s → {current_price:.8f} USDT"
            )
            break

def should_refresh(last_refresh, now):
    return (now - last_refresh).total_seconds() >= REFRESH_INTERVAL


def refresh_upcoming_currencies(upcoming_currencies, processed, last_refresh, now):
    try:
        for currencie,launch_date in fetch_upcoming_currencies(UPCOMING_TOKENS_URL).items():
            if currencie not in upcoming_currencies:
                print(f"[{now.isoformat()}] + New upcoming: {currencie} at {launch_date.isoformat()}")
            elif upcoming_currencies[currencie] != launch_date and currencie not in processed:
                print(f"[{now.isoformat()}] → Updated launch: {currencie} at {launch_date.isoformat()}")
            upcoming_currencies[currencie] = launch_date
        return now  
    except Exception as e:
        print(f"[{now.isoformat()}] ERROR fetching upcoming: {e}", file=sys.stderr)
        return last_refresh  


def check_tracked_currencies_launch(upcoming_currencies, processed_currencies, now):
    for currencie, launch_date in upcoming_currencies.items():
        if currencie in processed_currencies:
            continue
        if now >= launch_date:
            threading.Thread(target=check_currencie_at_launch, args=(currencie,), daemon=True).start()
            processed_currencies.add(currencie)


def tracker_loop():
    upcoming_currencies = {}
    processed_currencies = set()
    last_refresh = datetime.min.replace(tzinfo=timezone.utc)

    while True:
        now = datetime.now(timezone.utc)
        check_tracked_currencies_launch(upcoming_currencies, processed_currencies, now)

        if should_refresh(last_refresh, now):
            last_refresh = refresh_upcoming_currencies(upcoming_currencies, processed_currencies, last_refresh, now)

        time.sleep(FLUCTUATION_CHECK_INTERVAL)


def main():
    print()
    print("\n---------------------------------------------------CURRENCIE TRACKER STARTED---------------------------------------------------\n")
    print(f"-REFRESH_INTERVAL: {REFRESH_INTERVAL}s\n-FLUCTUATION_THRESHOLD {FLUCTUATION_THRESHOLD}%")
    print("_______________________________________________________________________________________________________________________________\n")
    
    try:
        tracker_loop()
    except KeyboardInterrupt:
        print("\nExecution interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()