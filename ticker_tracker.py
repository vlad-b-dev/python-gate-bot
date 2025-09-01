import json
import time
import logging
from datetime import datetime, timezone, timedelta
from collections import deque

from config import MAX_FLUCTUATION_WINDOW, WEB_SOCKET_URL

PRICE_SHOCK_PCT = 0.10           
ONE_MINUTE_SEC = 60              
FIVE_MINUTES_SEC = 300           
MIN_SAMPLES_FOR_ALERT = 10       
VOLATILITY_MULTIPLIER = 1.5      
VOLUME_SPIKE_MULTIPLIER = 3.5   
VOLUME_SPIKE_MIN_THRESHOLD = 10000

class TickerTracker:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.ws = None

        # 3-hour monitoring window
        self.initial_time = None
        self.window = timedelta(seconds=MAX_FLUCTUATION_WINDOW)

        # Rolling buffers
        self._recent_prices_1m = deque()
        self._recent_prices_5m = deque()
        self._recent_sum_1m = 0.0  

        self._recent_volumes_1m = deque()  
        self._recent_sum_vol_1m = 0.0      

        # Para calcular el delta de volumen
        self._last_base_volume = None  

    def _on_open(self, ws):
        payload = {
            "time": int(time.time()),
            "channel": "spot.tickers",
            "event": "subscribe",
            "payload": [f"{self.symbol}_USDT"]
        }
        ws.send(json.dumps(payload))

    def _prune_old_prices(self, now_ts: float):
        cutoff_1m = now_ts - ONE_MINUTE_SEC
        while self._recent_prices_1m and self._recent_prices_1m[0][0] < cutoff_1m:
            _, old_price = self._recent_prices_1m.popleft()
            self._recent_sum_1m -= old_price

        cutoff_5m = now_ts - FIVE_MINUTES_SEC
        while self._recent_prices_5m and self._recent_prices_5m[0][0] < cutoff_5m:
            self._recent_prices_5m.popleft()
        
        cutoff_vol = now_ts - ONE_MINUTE_SEC
        while self._recent_volumes_1m and self._recent_volumes_1m[0][0] < cutoff_vol:
            _, old_vol = self._recent_volumes_1m.popleft()
            self._recent_sum_vol_1m -= old_vol

    def _compute_avg_1m(self):
        n = len(self._recent_prices_1m)
        return self._recent_sum_1m / n if n > 0 else None

    def _compute_avg_vol_1m(self):
        n = len(self._recent_volumes_1m)
        return self._recent_sum_vol_1m / n if n > 0 else None

    def _on_message(self, ws, message):
        data = json.loads(message)
        if data.get("channel") != "spot.tickers" or data.get("event") != "update":
            return

        now_dt = datetime.now(timezone.utc)
        now_ts = now_dt.timestamp()
        info = data.get("result", {})

        try:
            price = float(info["last"])
        except (KeyError, ValueError, TypeError):
            return  

        # volumen acumulado (24h)
        try:
            base_volume_24h = float(info["base_volume"])
        except (KeyError, ValueError, TypeError):
            base_volume_24h = None

        # calcular delta de volumen entre ticks
        if base_volume_24h is not None and self._last_base_volume is not None:
            delta_volume = max(base_volume_24h - self._last_base_volume, 0.0)
        else:
            delta_volume = 0.0

        self._last_base_volume = base_volume_24h

        logging.info(f" Tick {self.symbol}")
        logging.info(f" PRICE → {price:.8f} USDT")
        logging.info(f" DELTA_VOLUME → {delta_volume:.8f} \n")

        if self.initial_time is None:
            self.initial_time = now_dt
            logging.info(f"✅ Connected for {self.symbol} — monitoring first 3h window")

        # Update rolling buffers
        self._recent_prices_1m.append((now_ts, price))
        self._recent_sum_1m += price

        self._recent_prices_5m.append((now_ts, price))

        self._recent_volumes_1m.append((now_ts, delta_volume))
        self._recent_sum_vol_1m += delta_volume

        # Prune old data
        self._prune_old_prices(now_ts)

        # —— Price Shock Check (1-minute) —— 
        avg_1m = self._compute_avg_1m()
        n_1m = len(self._recent_prices_1m)
        if avg_1m and n_1m >= MIN_SAMPLES_FOR_ALERT and avg_1m != 0:
            pct_dev = abs(price - avg_1m) / avg_1m
            if pct_dev > PRICE_SHOCK_PCT:
                print(
                    f"[{now_dt.isoformat()}] 🔔 PRICE SHOCK {self.symbol}: "
                    f"last={price:.8f}, avg_1m={avg_1m:.8f}, Δ={pct_dev*100:.2f}%"
                )

        # —— Volatility Breakout Check (5-minute) —— 
        n_5m = len(self._recent_prices_5m)
        if n_5m >= MIN_SAMPLES_FOR_ALERT:
            prices_5m = [p for ts, p in self._recent_prices_5m]
            high, low = max(prices_5m), min(prices_5m)
            range_5m = high - low
            upper_breakout = high + VOLATILITY_MULTIPLIER * range_5m
            lower_breakout = low - VOLATILITY_MULTIPLIER * range_5m
            
            if price > upper_breakout or price < lower_breakout:                
                print(
                    f"[{now_dt.isoformat()}] 🚀 VOLATILITY BREAKOUT {self.symbol}: "
                    f"last={price:.8f}, range=({low:.8f}-{high:.8f}), "
                    f"VOLATILITY_MULTIPLIER={VOLATILITY_MULTIPLIER:.8f}"
                )

        # —— Volume Spike Check (1-minute) —— 
        avg_vol_1m = self._compute_avg_vol_1m()
        if avg_vol_1m and avg_vol_1m > 0 and delta_volume > VOLUME_SPIKE_MULTIPLIER * avg_vol_1m and delta_volume > VOLUME_SPIKE_MIN_THRESHOLD:
            print(
                f"[{now_dt.isoformat()}] 📈 VOLUME SPIKE {self.symbol}: "
                f"last_volume={delta_volume:.8f}, avg_1m={avg_vol_1m:.8f}, "
                f"multiplier={VOLUME_SPIKE_MULTIPLIER}"
            )

        # —— Close socket after 3h window —— 
        if self.initial_time and (now_dt - self.initial_time) >= self.window:
            print(
                f"[{now_dt.isoformat()}] ℹ️ {self.symbol} window elapsed "
                f"({MAX_FLUCTUATION_WINDOW}s); last price: {price:.8f} USDT"
            )
            ws.close()

    def _on_error(self, ws, error):
        logging.info(f"ERROR websocket {self.symbol}: {error}")

    def start(self):
        import websocket  
        self.ws = websocket.WebSocketApp(
            WEB_SOCKET_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error
        )
        self.ws.run_forever()
