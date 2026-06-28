"""
config.py — Central configuration for ST Paper Trader
All tuneable parameters live here.
"""
import os

# ── Kite Connect ──────────────────────────────────────────────
KITE_API_KEY       = os.environ["KITE_API_KEY"]
KITE_ACCESS_TOKEN  = os.environ["KITE_ACCESS_TOKEN"]

# ── Telegram ──────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

# ── Strategy Parameters ───────────────────────────────────────
ST_LENGTH          = 80          # SuperTrend ATR length
ST_MULTIPLIER      = 15          # SuperTrend multiplier
MIN_DAY_CHANGE_PCT = -5.0        # Signal filter: Day % change must be ≤ this
PROFIT_TARGET_PCT  = 5.0         # Exit at +5% from entry (signal day Close)
MAX_HOLD_DAYS      = 30          # Force-exit after 30 calendar days
MIN_CANDLES        = 60          # Minimum candle history required

# ── Exchange / Segment ────────────────────────────────────────
# Kite instrument exchange prefix for NSE equities
EXCHANGE           = "NSE"

# ── Paths ─────────────────────────────────────────────────────
BASE_DIR           = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRADES_FILE        = os.path.join(BASE_DIR, "data", "open_trades.json")
CLOSED_FILE        = os.path.join(BASE_DIR, "data", "closed_trades.json")
LOG_FILE           = os.path.join(BASE_DIR, "data", "run.log")

# ── WebSocket / Polling (Render service) ─────────────────────
POLL_INTERVAL_SEC  = 60          # Re-fetch LTP every 60 seconds
MARKET_OPEN        = "09:15"     # IST
MARKET_CLOSE       = "15:30"     # IST
