"""
telegram.py — Send formatted messages to Telegram Bot.

Uses the Bot API sendMessage endpoint (no library dependency).
All messages are HTML-formatted for rich display.
"""

import logging
import requests
from datetime import date
from typing import Dict, List, Optional

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def _send(text: str, disable_preview: bool = True) -> bool:
    """Low-level send. Returns True on success."""
    payload = {
        "chat_id":                  TELEGRAM_CHAT_ID,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": disable_preview,
    }
    try:
        r = requests.post(API_URL, json=payload, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


# ── Alert: New Signal Detected ────────────────────────────────

def alert_new_signal(signal: Dict) -> bool:
    ohlc = signal["entry_day_ohlc"]
    text = (
        f"🔴 <b>NEW SIGNAL — ST BEARISH CROSSOVER</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Stock     :</b> <code>{signal['stock']}</code>\n"
        f"📅 <b>Date      :</b> {signal['signal_date']}\n"
        f"\n"
        f"<b>Entry (Signal Close)  :</b> ₹{signal['entry_price']:.2f}\n"
        f"<b>🎯 Target (+5%)       :</b> ₹{signal['target_price']:.2f}\n"
        f"<b>Day Change %          :</b> {signal['day_change_pct']:+.2f}%\n"
        f"\n"
        f"<b>Candle OHLC</b>\n"
        f"  O: ₹{ohlc['O']:.2f}  H: ₹{ohlc['H']:.2f}\n"
        f"  L: ₹{ohlc['L']:.2f}  C: ₹{ohlc['C']:.2f}\n"
        f"\n"
        f"<b>ST Value  :</b> {signal['st_value']:.2f}\n"
        f"<b>Prev ST   :</b> {signal['prev_st']:.2f}\n"
        f"<b>Prev Close:</b> ₹{signal['prev_close']:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ Watch window: 30 calendar days from signal date"
    )
    return _send(text)


# ── Alert: Target Hit (intraday) ──────────────────────────────

def alert_target_hit(trade: Dict, ltp: float) -> bool:
    entry      = trade["entry_price"]
    target     = trade["target_price"]
    pnl_pct    = (ltp - entry) / entry * 100
    days_held  = (date.today() - date.fromisoformat(trade["signal_date"])).days

    text = (
        f"✅ <b>TARGET HIT — PAPER EXIT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Stock      :</b> <code>{trade['stock']}</code>\n"
        f"📅 <b>Signal Date:</b> {trade['signal_date']}\n"
        f"📅 <b>Exit Date  :</b> {date.today().isoformat()}\n"
        f"\n"
        f"<b>Entry Price :</b> ₹{entry:.2f}\n"
        f"<b>Target Price:</b> ₹{target:.2f}\n"
        f"<b>Exit LTP    :</b> ₹{ltp:.2f}\n"
        f"\n"
        f"<b>📈 P&L       :</b> <b>{pnl_pct:+.2f}%</b>  🎉\n"
        f"<b>Days Held   :</b> {days_held}d\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    return _send(text)


# ── Alert: Trade Expired (30-day timeout) ────────────────────

def alert_trade_expired(trade: Dict, exit_price: float) -> bool:
    entry     = trade["entry_price"]
    pnl_pct   = (exit_price - entry) / entry * 100
    emoji     = "📈" if pnl_pct >= 0 else "📉"

    text = (
        f"⏰ <b>TRADE EXPIRED — 30-DAY TIMEOUT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Stock      :</b> <code>{trade['stock']}</code>\n"
        f"📅 <b>Signal Date:</b> {trade['signal_date']}\n"
        f"📅 <b>Exit Date  :</b> {date.today().isoformat()}\n"
        f"\n"
        f"<b>Entry Price :</b> ₹{entry:.2f}\n"
        f"<b>Target Price:</b> ₹{trade['target_price']:.2f}  <i>(not reached)</i>\n"
        f"<b>Exit Price  :</b> ₹{exit_price:.2f}  <i>(EOD Close)</i>\n"
        f"\n"
        f"<b>{emoji} P&L       :</b> <b>{pnl_pct:+.2f}%</b>\n"
        f"<b>Days Held   :</b> 30d\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    return _send(text)


# ── EOD Full Report ───────────────────────────────────────────

def send_eod_report(
    new_signals:     List[Dict],
    open_trades:     List[Dict],
    closed_today:    List[Dict],
    summary:         Dict,
    today_str:       str,
    current_prices:  Dict[str, float]   # symbol → current close
) -> bool:
    """
    Full end-of-day Telegram report.
    Sections:
      1. New signals today
      2. Open trades with current P&L
      3. Trades closed today
      4. Overall stats
    """
    lines = [
        f"📊 <b>EOD REPORT — {today_str}</b>",
        f"<b>ST(50,17) Bearish Crossover | Paper Trading</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    # ── Section 1: New Signals ────────────────────────────────
    lines.append(f"\n🔴 <b>NEW SIGNALS TODAY  ({len(new_signals)})</b>")
    if new_signals:
        for s in new_signals:
            lines.append(
                f"  • <code>{s['stock']:<14}</code>  "
                f"Entry ₹{s['entry_price']:.2f}  "
                f"Day% <b>{s['day_change_pct']:+.2f}%</b>  "
                f"→ Target ₹{s['target_price']:.2f}"
            )
    else:
        lines.append("  <i>No new signals today</i>")

    # ── Section 2: Open Trades ────────────────────────────────
    lines.append(f"\n📂 <b>OPEN TRADES  ({len(open_trades)})</b>")
    if open_trades:
        for t in open_trades:
            cp      = current_prices.get(t["stock"])
            sig_dt  = date.fromisoformat(t["signal_date"])
            days    = (date.today() - sig_dt).days
            rem     = max(0, 30 - days)

            if cp is not None:
                unr_pct = (cp - t["entry_price"]) / t["entry_price"] * 100
                pnl_str = f"Unr {unr_pct:+.2f}%"
                ltp_str = f"LTP ₹{cp:.2f}"
            else:
                pnl_str = "LTP N/A"
                ltp_str = ""

            lines.append(
                f"  • <code>{t['stock']:<14}</code>  "
                f"Entry ₹{t['entry_price']:.2f}  "
                f"Tgt ₹{t['target_price']:.2f}  "
                f"{ltp_str}  <b>{pnl_str}</b>  "
                f"Day {days}/30  ({rem}d left)"
            )
    else:
        lines.append("  <i>No open trades</i>")

    # ── Section 3: Closed Today ───────────────────────────────
    lines.append(f"\n✅ <b>CLOSED TODAY  ({len(closed_today)})</b>")
    if closed_today:
        for t in closed_today:
            pnl   = t.get("pnl_pct", 0)
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(
                f"  {emoji} <code>{t['stock']:<14}</code>  "
                f"Entry ₹{t['entry_price']:.2f} → Exit ₹{t['exit_price']:.2f}  "
                f"<b>{pnl:+.2f}%</b>  "
                f"[{t['exit_reason']}]  {t['days_held']}d"
            )
    else:
        lines.append("  <i>No trades closed today</i>")

    # ── Section 4: Overall Stats ──────────────────────────────
    lines.append("\n📈 <b>OVERALL STATS</b>")
    lines.append(f"  Total Closed   : {summary['closed_total']}")
    lines.append(f"  Target Hits    : {summary['target_hits']}  |  Expired: {summary['expired']}")
    lines.append(f"  Win Rate       : <b>{summary['win_rate_pct']:.1f}%</b>")
    lines.append(f"  Avg P&L        : <b>{summary['avg_pnl_pct']:+.2f}%</b>")
    lines.append(f"  Best Trade     : <b>{summary['best_pnl']:+.2f}%</b>")
    lines.append(f"  Worst Trade    : <b>{summary['worst_pnl']:+.2f}%</b>")
    lines.append(f"  Open Now       : {summary['open_count']}")
    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    return _send("\n".join(lines))
