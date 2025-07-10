#!/usr/bin/env python3
# main.py

import requests
from bs4 import BeautifulSoup
import re
import sys

def fetch_upcoming(url):
    """
    Fetch the page at `url`, parse out all the rows marked
    data-new="true", and return a list of (name, launch_datetime) tuples.
    """
    resp = requests.get(url)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, 'lxml')
    upcoming = []

    # Each row in the table body
    for row in soup.select('tbody tr'):
        # look for the <span label="…">COINNAME</span>
        name_tag = row.select_one('span[label]')
        if not name_tag:
            continue
        name = name_tag.text.strip()

        # look for the first span in the *next* cell which contains an ISO‐date
        # e.g. "2025-07-10 14:00:00"
        date_span = row.select_one('td + td span')
        if not date_span:
            continue

        m = re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', date_span.text)
        if not m:
            continue
        launch_dt = m.group(0)

        upcoming.append((name, launch_dt))

    return upcoming

def main():
    URL = "https://www.gate.com/es/price/view/new-cryptocurrencies"
    try:
        items = fetch_upcoming(URL)
    except Exception as e:
        print("Error fetching or parsing:", e, file=sys.stderr)
        sys.exit(1)

    if not items:
        print("No upcoming currencies found.")
        return

    print("Upcoming currencies:")
    for name, dt in items:
        print(f" • {name:10s}  →  {dt}")

if __name__ == "__main__":
    main()
