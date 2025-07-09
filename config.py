# config.py

# List the spot tokens you care about (e.g. 'WLD', 'ETH', 'SOL')
TARGET_TOKENS = ["WLD", "ETH", "SOL"]

# Map spot token → futures contract symbol (we’ll assume USDT‑settled)
# e.g. "WLD" → "WLD_USDT"
FUTURES_SUFFIX = "_USDT"
