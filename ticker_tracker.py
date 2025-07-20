# ticker_tracker.py

import json
import time
import sys
from datetime import datetime, timezone, timedelta

from config import FLUCTUATION_THRESHOLD, MAX_FLUCTUATION_WINDOW, WEB_SOCKET_URL

class TickerTracker:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.ws = None
        self.initial_price = None
        self.initial_time = None
        self.window = timedelta(seconds=MAX_FLUCTUATION_WINDOW)

    def _on_open(self, ws):
        payload = {
            "time": int(time.time()),
            "channel":"spot.tickers",
            "event": "subscribe",
            "payload": [f"{self.symbol}_USDT"]
        }
        ws.send(json.dumps(payload))

    def _on_message(self, ws, message):
        data = json.loads(message)
        if data.get("channel") != "spot.tickers":
            return

        for entry in data.get("result", []):
            _, last_price, *_, _ = entry
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
                ws.close()
                return

            if now - self.initial_time >= self.window:
                print(
                    f"[{now.isoformat()}] ℹ️ {self.symbol} window elapsed ({MAX_FLUCTUATION_WINDOW}s); final price: {price:.8f} USDT"
                )
                ws.close()
                return

    def _on_error(self, ws, error):
        now = datetime.now(timezone.utc)
        print(f"[{now.isoformat()}] ERROR websocket {self.symbol}: {error}", file=sys.stderr)

    def start(self):
        import websocket  # defer until start() is called
        self.ws = websocket.WebSocketApp(
            WEB_SOCKET_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error
        )
        self.ws.run_forever()
