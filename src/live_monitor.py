"""
live_monitor.py — Persistent intraday monitor (runs on Render).

Polls LTP for all open trades every POLL_INTERVAL_SEC seconds
during market hours (09:15–15:30 IST).

When a trade's target price (entry × 1.05) is touched:
  → Log exit in TradeStore as TARGET_HIT
  → Send Telegram alert immediately
  → Remove from open trades (no more monitoring needed)

This process runs 24×7 on Render (free/starter dyno).
Outside market hours it sleeps and waits.
"""

import logging
import sys
import os
import time
from datetime import date, datetime, time as dt_time
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    TRADES_FILE, CLOSED_FILE,
    POLL_INTERVAL_SEC, MARKET_OPEN, MARKET_CLOSE
)
from kite_client import KiteClient
from trade_store import TradeStore
from telegram import alert_target_hit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("live_monitor")

IST = ZoneInfo("Asia/Kolkata")

_MARKET_OPEN_TIME  = dt_time(9, 15)
_MARKET_CLOSE_TIME = dt_time(15, 30)


def is_market_open() -> bool:
    now = datetime.now(IST).time()
    return _MARKET_OPEN_TIME <= now <= _MARKET_CLOSE_TIME


def seconds_until_market_open() -> int:
    now    = datetime.now(IST)
    target = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if now.time() > _MARKET_CLOSE_TIME:
        # Next day
        target = (now + __import__("datetime").timedelta(days=1)).replace(
            hour=9, minute=15, second=0, microsecond=0
        )
    delta = (target - now).total_seconds()
    return max(0, int(delta))


def run():
    logger.info("Live monitor starting on Render …")

    kite  = KiteClient()
    store = TradeStore(TRADES_FILE, CLOSED_FILE)

    kite.load_instruments()
    logger.info("Instruments loaded. Entering monitoring loop.")

    while True:
        if not is_market_open():
            wait = seconds_until_market_open()
            logger.info(f"Market closed. Sleeping {wait}s until 09:15 IST …")
            time.sleep(min(wait, 3600))      # wake up at least hourly
            continue

        open_trades = store.load_open()

        if not open_trades:
            logger.debug("No open trades. Sleeping …")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        # Build token list for LTP batch fetch
        tokens = [t["instrument_token"] for t in open_trades if t.get("instrument_token")]
        if not tokens:
            time.sleep(POLL_INTERVAL_SEC)
            continue

        ltp_map = kite.get_ltp(tokens)        # {token: ltp}

        for trade in list(open_trades):
            token  = trade.get("instrument_token")
            ltp    = ltp_map.get(token)

            if ltp is None:
                continue

            target = trade["target_price"]

            if ltp >= target:
                # ── TARGET HIT ────────────────────────────────
                signal_date = date.fromisoformat(trade["signal_date"])
                days_held   = (date.today() - signal_date).days

                closed = store.close_trade(
                    trade_id    = trade["id"],
                    exit_price  = ltp,
                    exit_date   = date.today().isoformat(),
                    exit_reason = "TARGET_HIT",
                    days_held   = days_held
                )

                alert_target_hit(trade, ltp)

                logger.info(
                    f"TARGET HIT: {trade['stock']}  "
                    f"Entry ₹{trade['entry_price']:.2f}  "
                    f"LTP ₹{ltp:.2f}  "
                    f"Target ₹{target:.2f}  "
                    f"PnL {closed['pnl_pct']:+.2f}%  "
                    f"Days {days_held}"
                )
            else:
                pct_away = (target - ltp) / ltp * 100
                logger.debug(
                    f"{trade['stock']}  LTP ₹{ltp:.2f}  "
                    f"Target ₹{target:.2f}  ({pct_away:.2f}% away)"
                )

        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    run()
