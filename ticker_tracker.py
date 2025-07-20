# ticker_tracker.py

import json
import time
import sys
from datetime import datetime, timezone, timedelta

import websocket

from config import FLUCTUATION_THRESHOLD, MAX_FLUCTUATION_WINDOW, WEB_SOCKET_URL


class TickerTracker:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.web_socket = None
        self.initial_price = None
        self.initial_time = None
        self.window = timedelta(seconds=MAX_FLUCTUATION_WINDOW)

    def _on_open(self, web_socket):
        payload = {
            "time": int(time.time()),
            "channel": "tickers",
            "event": "subscribe",
            "payload": [f"{self.symbol}_USDT"]
        }
        web_socket.send(json.dumps(payload))

    def _on_message(self, web_socket, message):
        data = json.loads(message)
        if data.get("channel") != "tickers":
            return

        for entry in data.get("result", []):
            symbol, last_price, *_, ts = entry
            now = datetime.now(timezone.utc)
            price = float(last_price)
            if self.initial_price is None:
                self.initial_price = price
                self.initial_time = now
                print(f"[{now.isoformat()}] ✅ Connected for {self.symbol} — initial price: {price:.8f} USDT")
                return

            elapsed = (now - self.initial_time).total_seconds()
            if elapsed <= 0:
                return

            speed = ((price - self.initial_price) / self.initial_price * 100) / elapsed

            if abs(speed) >= FLUCTUATION_THRESHOLD:
                print(
                    f"[{now.isoformat()}] ⚠️ {self.symbol} speed {speed:+.2f}%/s over {int(elapsed)}s → {price:.8f} USDT"
                )
                web_socket.close()
                return

            if now - self.initial_time >= self.window:
                print(
                    f"[{now.isoformat()}] ℹ️ {self.symbol} window elapsed ({MAX_FLUCTUATION_WINDOW}s); final price: {price:.8f} USDT"
                )
                web_socket.close()
                return

    def _on_error(self, web_socket, error):
        now = datetime.now(timezone.utc)
        print(f"[{now.isoformat()}] ERROR websocket {self.symbol}: {error}", file=sys.stderr)

    def start(self):
        self.web_socket = websocket.WebSocketApp(
            WEB_SOCKET_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error
        )
        self.web_socket.run_forever()