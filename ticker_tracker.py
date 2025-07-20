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
        # Only handle ticker messages
        if data.get("channel") != "spot.tickers":
            return

        now = datetime.now(timezone.utc)

        print("PRUEBA SE LLEGA AQUI")
        print(f"[{data}]")
                
        results = data.get("result")
        if results is None:
            return

        # Normalize entries: snapshot dict or list of lists
        entries = []
        if isinstance(results, dict):
            # Initial snapshot comes as a dict of symbol: info
            for pair, info in results.items():
                entries.append((pair, info))
        elif isinstance(results, list):
            entries = results
        else:
            return

        for entry in entries:
            # Extract price
            try:
                if isinstance(entry, tuple):
                    # Snapshot entry: (pair, info dict)
                    _, info = entry
                    price = float(info.get('last', 0))
                elif isinstance(entry, list) or isinstance(entry, tuple):
                    # Update entry: [pair, last_price, ...]
                    price = float(entry[1])
                else:
                    continue
            except (ValueError, TypeError):
                # Skip non-numeric
                continue

            # Initialize on first valid tick
            if self.initial_price is None:
                self.initial_price = price
                self.initial_time = now
                print(f"[{now.isoformat()}] ✅ Connected for {self.symbol} — initial price: {price:.8f} USDT")
                return

            elapsed = (now - self.initial_time).total_seconds()
            if elapsed <= 0:
                continue

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
                return

    def _on_error(self, ws, error):
        now = datetime.now(timezone.utc)
        print(f"[{now.isoformat()}] ERROR websocket {self.symbol}: {error}", file=sys.stderr)

    def start(self):
        import websocket  # defer until start()
        self.ws = websocket.WebSocketApp(
            WEB_SOCKET_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error
        )
        self.ws.run_forever()
