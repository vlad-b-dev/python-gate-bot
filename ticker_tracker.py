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
        # Subscribe to the ticker channel for the symbol
        payload = {
            "time": int(time.time()),
            "channel": "spot.tickers",
            "event": "subscribe",
            "payload": [f"{self.symbol}_USDT"]
        }
        ws.send(json.dumps(payload))

    def _on_message(self, ws, message):
        data = json.loads(message)
        # Only process real ticker updates; ignore subscribe confirmations
        if data.get("channel") != "spot.tickers" or data.get("event") != "update":
            return

        now = datetime.now(timezone.utc)
        info = data.get("result", {})

        # Extract the last price
        try:
            price = float(info["last"])
        except (KeyError, ValueError, TypeError):
            # missing or invalid price → skip
            return

        # —— LOG EVERY PRICE UPDATE —— 
        logging.info(f"ℹ️ {self.symbol} price tick → {price:.8f} USDT")

        # On first tick, record initial values
        if self.initial_price is None:
            self.initial_price = price
            self.initial_time = now
            logging.info(f"✅ Connected for {self.symbol} — initial price: {price:.8f} USDT")
            return

        elapsed = (now - self.initial_time).total_seconds()
        if elapsed <= 0:
            return

        speed = ((price - self.initial_price) / self.initial_price * 100) / elapsed

        # Threshold breach
        if abs(speed) >= FLUCTUATION_THRESHOLD:
            print(
                f"[{now.isoformat()}] ⚠️ {self.symbol} speed {speed:+.2f}%/s over {int(elapsed)}s → {price:.8f} USDT"
            )
            ws.close()
            return

        # Max window elapsed
        if now - self.initial_time >= self.window:
            print(
                f"[{now.isoformat()}] ℹ️ {self.symbol} window elapsed ({MAX_FLUCTUATION_WINDOW}s); final price: {price:.8f} USDT"
            )
            ws.close()

    def _on_error(self, ws, error):
        logging.info(f"ERROR websocket {self.symbol}: {error}")

    def start(self):
        import websocket  # defer until start() is called
        self.ws = websocket.WebSocketApp(
            WEB_SOCKET_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error
        )
        self.ws.run_forever()
