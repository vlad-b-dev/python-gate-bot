import json
import time
import logging
from datetime import datetime, timezone, timedelta
from collections import deque
import statistics

from config import MAX_FLUCTUATION_WINDOW, WEB_SOCKET_URL

PRICE_SHOCK_PCT = 0.10
ONE_MINUTE_SEC = 60
FIVE_MINUTES_SEC = 300
MIN_SAMPLES_FOR_ALERT = 10
VOLATILITY_MULTIPLIER = 2
VOLUME_SPIKE_MULTIPLIER = 3.5
VOLUME_SPIKE_MIN_THRESHOLD = 10000
SPREAD_MULTIPLIER_HIGH = 3.5
SPREAD_MULTIPLIER_LOW = 0.2


class TickerTracker:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.ws = None
        self.initial_time = None
        self.window = timedelta(seconds=MAX_FLUCTUATION_WINDOW)

        # Rolling buffers
        self._recent_prices_1m = deque()
        self._recent_sum_1m = 0.0
        self._recent_prices_5m = deque()
        self._recent_volumes_1m = deque()
        self._recent_sum_vol_1m = 0.0
        self._last_base_volume = None
        self._recent_spreads_10m = deque()

    # ---------- WebSocket Handlers ----------
    def _on_open(self, ws):
        payload = {
            "time": int(time.time()),
            "channel": "spot.tickers",
            "event": "subscribe",
            "payload": [f"{self.symbol}_USDT"],
        }
        ws.send(json.dumps(payload))

    def _on_error(self, ws, error):
        logging.info(f"ERROR websocket {self.symbol}: {error}")

    def start(self):
        import websocket

        self.ws = websocket.WebSocketApp(
            WEB_SOCKET_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
        )
        self.ws.run_forever()

    # ---------- Helpers ----------
    def _prune_old_data(self, now_ts: float):
        """Elimina datos antiguos de los buffers para rolling windows."""
        cutoff_1m = now_ts - ONE_MINUTE_SEC
        cutoff_5m = now_ts - FIVE_MINUTES_SEC
        cutoff_vol = now_ts - ONE_MINUTE_SEC
        cutoff_spread = now_ts - 600  # 10 minutos

        for buffer, sum_attr, cutoff in [
            (self._recent_prices_1m, "_recent_sum_1m", cutoff_1m),
            (self._recent_volumes_1m, "_recent_sum_vol_1m", cutoff_vol),
        ]:
            while buffer and buffer[0][0] < cutoff:
                ts, val = buffer.popleft()
                setattr(self, sum_attr, getattr(self, sum_attr) - val)

        while self._recent_prices_5m and self._recent_prices_5m[0][0] < cutoff_5m:
            self._recent_prices_5m.popleft()

        while (
            self._recent_spreads_10m and self._recent_spreads_10m[0][0] < cutoff_spread
        ):
            self._recent_spreads_10m.popleft()

    def _compute_avg(self, buffer, sum_attr):
        n = len(buffer)
        return getattr(self, sum_attr) / n if n > 0 else None

    # ---------- Main Message Handler ----------
    def _on_message(self, ws, message):

        data = json.loads(message)
        if data.get("channel") != "spot.tickers" or data.get("event") != "update":
            return

        now_dt = datetime.now(timezone.utc)
        now_ts = now_dt.timestamp()
        info = data.get("result", {})

        try:
            price = float(info["last"])
            highest_bid = float(info["highest_bid"])
            lowest_ask = float(info["lowest_ask"])
        except (KeyError, ValueError, TypeError):
            return

        # Calcular delta de volumen
        try:
            base_volume_24h = float(info["base_volume"])
        except (KeyError, ValueError, TypeError):
            base_volume_24h = None

        if base_volume_24h is not None and self._last_base_volume is not None:
            delta_volume = max(base_volume_24h - self._last_base_volume, 0.0)
        else:
            delta_volume = 0.0
        self._last_base_volume = base_volume_24h

        # Logging
        logging.info(f" Tick {self.symbol}")
        logging.info(f" PRICE → {price:.8f} USDT")
        logging.info(f" DELTA_VOLUME → {delta_volume:.8f} \n")

        if self.initial_time is None:
            self.initial_time = now_dt
            logging.info(f"✅ Connected for {self.symbol} — monitoring first 3h window")

        # ---------- Update Buffers ----------
        self._recent_prices_1m.append((now_ts, price))
        self._recent_sum_1m += price
        self._recent_prices_5m.append((now_ts, price))
        self._recent_volumes_1m.append((now_ts, delta_volume))
        self._recent_sum_vol_1m += delta_volume
        spread = lowest_ask - highest_bid
        self._recent_spreads_10m.append((now_ts, spread))

        # Prune old data
        self._prune_old_data(now_ts)

        # ---------- Alerts ----------
        self._check_price_shock(now_dt, price)
        self._check_volatility_breakout(now_dt, price)
        self._check_volume_spike(now_dt, delta_volume)
        self._check_spread_anomaly(now_dt, spread)

        # Close socket after monitoring window
        if self.initial_time and (now_dt - self.initial_time) >= self.window:
            print(
                f"[{now_dt.isoformat()}] ℹ️ {self.symbol} window elapsed "
                f"({MAX_FLUCTUATION_WINDOW}s); last price: {price:.8f} USDT"
            )
            ws.close()

    # ---------- Alert Checks ----------
    def _check_price_shock(self, now_dt, price):
        avg_1m = self._compute_avg(self._recent_prices_1m, "_recent_sum_1m")
        if (
            avg_1m
            and len(self._recent_prices_1m) >= MIN_SAMPLES_FOR_ALERT
            and avg_1m != 0
        ):
            pct_dev = abs(price - avg_1m) / avg_1m
            if pct_dev > PRICE_SHOCK_PCT:
                print(
                    f"[{now_dt.isoformat()}] 🔔 PRICE SHOCK {self.symbol}: "
                    f"last={price:.8f}, avg_1m={avg_1m:.8f}, Δ={pct_dev*100:.2f}%"
                )

    def _check_volatility_breakout(self, now_dt, price):
        if len(self._recent_prices_5m) >= MIN_SAMPLES_FOR_ALERT:
            prices_5m = [p for ts, p in self._recent_prices_5m]
            mean_5m = statistics.mean(prices_5m)
            std_5m = statistics.pstdev(prices_5m)

            upper = mean_5m + VOLATILITY_MULTIPLIER * std_5m
            lower = mean_5m - VOLATILITY_MULTIPLIER * std_5m

            if price > upper or price < lower:
                print(
                    f"[{now_dt.isoformat()}] 🚀 VOLATILITY BREAKOUT {self.symbol}: "
                    f"last={price:.8f}, mean_5m={mean_5m:.8f}, std={std_5m:.8f}"
                )

    def _check_volume_spike(self, now_dt, delta_volume):
        avg_vol_1m = self._compute_avg(self._recent_volumes_1m, "_recent_sum_vol_1m")
        if (
            avg_vol_1m
            and avg_vol_1m > 0
            and delta_volume > VOLUME_SPIKE_MULTIPLIER * avg_vol_1m
            and delta_volume > VOLUME_SPIKE_MIN_THRESHOLD
        ):
            print(
                f"[{now_dt.isoformat()}] 📈 VOLUME SPIKE {self.symbol}: "
                f"last_volume={delta_volume:.8f}, avg_1m={avg_vol_1m:.8f}, "
                f"multiplier={VOLUME_SPIKE_MULTIPLIER}"
            )

    def _check_spread_anomaly(self, now_dt, spread):
        if len(self._recent_spreads_10m) >= MIN_SAMPLES_FOR_ALERT:
            spreads = [s for ts, s in self._recent_spreads_10m]
            median_spread = statistics.median(spreads)
            if median_spread > 0 and (
                spread > SPREAD_MULTIPLIER_HIGH * median_spread
                or spread < SPREAD_MULTIPLIER_LOW * median_spread
            ):
                print(
                    f"[{now_dt.isoformat()}] ⚠️ SPREAD ANOMALY {self.symbol}: "
                    f"current={spread:.8f}, median_10min={median_spread:.8f}"
                )
