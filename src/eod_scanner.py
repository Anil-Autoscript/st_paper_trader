"""
eod_scanner.py — End-of-day signal scanner.

Run context: GitHub Actions cron at 3:35 PM IST (10:05 UTC).

Flow:
  1. Load Nifty 500 symbols from KiteClient
  2. For each symbol → detect_signal()
  3. Any signal with day_change_pct ≤ -5% → add to TradeStore
  4. Check all open trades for 30-day expiry using today's EOD close
  5. Send full EOD Telegram report
"""

import logging
import sys
import os
from datetime import date, datetime, timedelta

# Allow running from src/ or project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    TRADES_FILE, CLOSED_FILE, MIN_DAY_CHANGE_PCT,
    PROFIT_TARGET_PCT, MAX_HOLD_DAYS
)
from kite_client import KiteClient
from trade_store import TradeStore
from telegram import (
    alert_new_signal, alert_trade_expired, send_eod_report
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("eod_scanner")


def run():
    today     = date.today()
    today_str = today.strftime("%d-%b-%Y")
    logger.info(f"EOD Scanner started — {today_str}")

    kite  = KiteClient()
    store = TradeStore(TRADES_FILE, CLOSED_FILE)

    kite.load_instruments()
    symbols = kite.nifty500_symbols()
    logger.info(f"Universe: {len(symbols)} symbols")

    # ── Step 1: Scan for new signals ──────────────────────────
    new_signals = []
    scan_errors = 0

    for symbol in symbols:
        token = kite.get_token(symbol)
        if not token:
            logger.debug(f"Token not found: {symbol}")
            continue

        try:
            signal = kite.detect_signal(symbol, token)
            if signal is None:
                continue

            if signal["day_change_pct"] > MIN_DAY_CHANGE_PCT:
                logger.debug(
                    f"{symbol}: signal found but day% {signal['day_change_pct']:+.2f}% "
                    f"doesn't meet threshold {MIN_DAY_CHANGE_PCT}%"
                )
                continue

            # Check we don't already have an open trade for this stock
            existing = store.get_open_by_stock(symbol)
            if existing:
                logger.info(f"{symbol}: already in open trades, skipping.")
                continue

            trade_id = f"{symbol}_{today.isoformat()}"
            trade = {
                "id":               trade_id,
                "stock":            signal["stock"],
                "instrument_token": signal["instrument_token"],
                "signal_date":      signal["signal_date"],
                "entry_price":      signal["entry_price"],
                "target_price":     signal["target_price"],
                "day_change_pct":   signal["day_change_pct"],
                "st_value":         signal["st_value"],
                "entry_day_ohlc":   signal["entry_day_ohlc"],
                "status":           "OPEN",
                "exit_price":       None,
                "exit_date":        None,
                "exit_reason":      None,
                "pnl_pct":          None,
                "days_held":        None,
            }

            store.add_trade(trade)
            new_signals.append(signal)
            alert_new_signal(signal)
            logger.info(
                f"NEW SIGNAL: {symbol}  Entry ₹{signal['entry_price']:.2f}  "
                f"Day% {signal['day_change_pct']:+.2f}%"
            )

        except Exception as e:
            scan_errors += 1
            logger.warning(f"Error scanning {symbol}: {e}")

    logger.info(
        f"Scan complete — {len(new_signals)} new signals, {scan_errors} errors"
    )

    # ── Step 2: Check open trades for 30-day expiry ───────────
    open_trades    = store.load_open()
    closed_today   = []
    current_prices = {}

    for trade in list(open_trades):       # iterate copy
        signal_date = date.fromisoformat(trade["signal_date"])
        days_held   = (today - signal_date).days

        if days_held < MAX_HOLD_DAYS:
            # Collect current price for EOD report
            q = kite.get_quote(trade["stock"])
            if q:
                current_prices[trade["stock"]] = q["ltp"]
            continue

        # ── 30-day expiry: exit at today's EOD close ──────────
        q = kite.get_quote(trade["stock"])
        if not q:
            logger.warning(f"Could not get quote for expired trade: {trade['stock']}")
            continue

        exit_price = q["close"] if q["close"] else q["ltp"]

        closed = store.close_trade(
            trade_id    = trade["id"],
            exit_price  = exit_price,
            exit_date   = today.isoformat(),
            exit_reason = "EXPIRED_30D",
            days_held   = days_held
        )
        if closed:
            closed_today.append(closed)
            alert_trade_expired(trade, exit_price)
            logger.info(
                f"EXPIRED: {trade['stock']}  Exit ₹{exit_price:.2f}  "
                f"PnL {closed['pnl_pct']:+.2f}%"
            )

    # ── Step 3: EOD Telegram report ───────────────────────────
    open_trades_now = store.load_open()

    # Supplement current_prices with any we haven't fetched yet
    for trade in open_trades_now:
        if trade["stock"] not in current_prices:
            q = kite.get_quote(trade["stock"])
            if q:
                current_prices[trade["stock"]] = q["ltp"]

    summary = store.summary()

    send_eod_report(
        new_signals    = new_signals,
        open_trades    = open_trades_now,
        closed_today   = closed_today,
        summary        = summary,
        today_str      = today_str,
        current_prices = current_prices,
    )

    logger.info("EOD report sent.")
    logger.info(
        f"Summary — Open: {summary['open_count']}  "
        f"Closed: {summary['closed_total']}  "
        f"Win Rate: {summary['win_rate_pct']}%"
    )


if __name__ == "__main__":
    run()
