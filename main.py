import time
import json
import threading
import requests
from bs4 import BeautifulSoup
from websocket import WebSocketApp

from config import TARGET_TOKENS, FUTURES_SUFFIX

# ──────────────── Fetch Upcoming Tokens ────────────────
NEW_COINS_URL = "https://www.gate.com/price/view/new-cryptocurrencies"

def fetch_upcoming_tokens():
    print("[*] Fetching upcoming tokens…", end=" ")
    try:
        resp = requests.get(NEW_COINS_URL, headers={"User-Agent": "python-requests"})
        resp.raise_for_status()
    except Exception as e:
        print("FAILED")
        print(f"[!] Error fetching list: {e}")
        return []
    print("OK")

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", class_="table-list")
    rows = table.tbody.find_all("tr") if table and table.tbody else []
    upcoming = []
    for tr in rows:
        cols = tr.find_all("td")
        # the “Opening time” column contains the countdown — only those not yet open
        open_time = cols[3].get_text(strip=True)
        if "Opening time" in open_time or ":" in open_time:
            name = cols[1].get_text(strip=True)
            upcoming.append((name, open_time))
    return upcoming

# ──────────────── Announcement listener ────────────────
ANN_URL = "wss://api.gateio.ws/ws/v4/ann"
ANN_CHANNEL = "announcement.summary_listing"

def on_ann_open(ws):
    print("[ANN] Connected to announcements")
    ws.send(json.dumps({
        "time": int(time.time()),
        "channel": ANN_CHANNEL,
        "event": "subscribe",
        "payload": ["en"]
    }))

def on_ann_message(ws, message):
    msg = json.loads(message)
    if msg.get("event") != "update":
        return
    title = msg["result"]["title"]
    print(f"[ANN] {title}")
    for token in TARGET_TOKENS:
        if f"({token})" in title:
            print(f"[ANN] Detected listing: {token}")
            threading.Thread(target=track_futures, args=(token + FUTURES_SUFFIX,), daemon=True).start()

def on_ann_error(ws, error):
    print(f"[ANN] Error: {error}")

def on_ann_close(ws, code, msg):
    print(f"[ANN] Disconnected (code={code})")

def start_announcement_ws():
    ws = WebSocketApp(
        ANN_URL,
        on_open=on_ann_open,
        on_message=on_ann_message,
        on_error=on_ann_error,
        on_close=on_ann_close,
    )
    ws.run_forever(ping_interval=20, ping_timeout=10)

# ──────────────── Futures ticker tracker ────────────────
FUT_URL = "wss://fx-ws.gateio.ws/v4/ws/usdt"
SPEED_THRESHOLD = 0.03  # 3% per second
MAX_DURATION = 60       # seconds

def track_futures(contract):
    start_price = None
    start_time = None

    def on_open(ws):
        print(f"[FUT] Subscribed to {contract}")
        ws.send(json.dumps({
            "time": int(time.time()),
            "channel": "futures.tickers",
            "event": "subscribe",
            "payload": [contract]
        }))

    def on_message(ws, message):
        nonlocal start_price, start_time
        msg = json.loads(message)
        if msg.get("event") != "update":
            return
        data = msg["result"][0]
        last = float(data["last"])
        now = time.time()

        if start_price is None:
            start_price = last
            start_time = now
            print(f"[FUT] {contract} first price: {last:.4f}")
            return

        elapsed = now - start_time
        pct = (last - start_price) / start_price * 100

        print(f"[FUT] {contract}: {last:.4f} ({pct:.2f}% in {elapsed:.1f}s)")

        if elapsed >= MAX_DURATION:
            print(f"[FUT] {contract}: time up, closing")
            ws.close()
            return

        speed = pct / elapsed
        if speed >= SPEED_THRESHOLD * 100:
            print(f"[ALERT] {contract}: {pct:.2f}% in {elapsed:.1f}s → {speed:.2f}%/s")
            ws.close()

    def on_error(ws, error):
        print(f"[FUT] {contract} error: {error}")

    def on_close(ws, code, msg):
        print(f"[FUT] {contract} disconnected (code={code})")

    ws = WebSocketApp(
        FUT_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    ws.run_forever(ping_interval=20, ping_timeout=10)

# ──────────────── Entry point ────────────────
if __name__ == "__main__":
    print("[*] Starting program")
    upcoming = fetch_upcoming_tokens()
    if upcoming:
        print(f"→ {len(upcoming)} upcoming tokens:")
        for name, ot in upcoming:
            print(f"   • {name.ljust(12)} launches at {ot}")
    else:
        print("→ No upcoming tokens found or unable to fetch list.")
    print("[*] Launching announcement listener…\n")
    start_announcement_ws()
