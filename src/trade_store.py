"""
trade_store.py — JSON-backed persistence for open and closed trades.

Schema for each trade record:
{
    "id":            "RELIANCE_2024-06-10",
    "stock":         "RELIANCE",
    "instrument_token": 738561,
    "signal_date":   "2024-06-10",
    "entry_price":   2850.00,        # Signal day Close
    "target_price":  2992.50,        # entry × 1.05
    "day_change_pct": -6.23,
    "st_value":      2920.00,
    "entry_day_ohlc": {"O": ..., "H": ..., "L": ..., "C": ...},
    "status":        "OPEN",         # OPEN | TARGET_HIT | EXPIRED
    "exit_price":    null,
    "exit_date":     null,
    "exit_reason":   null,           # "TARGET_HIT" | "EXPIRED_30D"
    "pnl_pct":       null,
    "days_held":     null
}
"""

import json
import os
import logging
from datetime import date, datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def _ensure_dir(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _load(path: str) -> List[Dict]:
    _ensure_dir(path)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        logger.warning(f"Could not read {path}, starting fresh.")
        return []


def _save(path: str, data: List[Dict]):
    _ensure_dir(path)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)           # atomic write


# ── Public API ────────────────────────────────────────────────

class TradeStore:
    def __init__(self, trades_file: str, closed_file: str):
        self.trades_file = trades_file
        self.closed_file = closed_file

    # ── Open trades ───────────────────────────────────────────

    def load_open(self) -> List[Dict]:
        return _load(self.trades_file)

    def save_open(self, trades: List[Dict]):
        _save(self.trades_file, trades)

    def add_trade(self, trade: Dict):
        """Append a new open trade. Deduplicated by id."""
        trades = self.load_open()
        existing_ids = {t["id"] for t in trades}
        if trade["id"] not in existing_ids:
            trades.append(trade)
            self.save_open(trades)
            logger.info(f"Added trade: {trade['id']}")
        else:
            logger.info(f"Skipped duplicate trade: {trade['id']}")

    def get_open_by_stock(self, stock: str) -> Optional[Dict]:
        for t in self.load_open():
            if t["stock"] == stock and t["status"] == "OPEN":
                return t
        return None

    # ── Close a trade ─────────────────────────────────────────

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_date: str,
        exit_reason: str,        # "TARGET_HIT" | "EXPIRED_30D"
        days_held: int
    ):
        trades = self.load_open()
        remaining = []
        closed_trade = None

        for t in trades:
            if t["id"] == trade_id:
                t["status"]      = exit_reason
                t["exit_price"]  = round(exit_price, 2)
                t["exit_date"]   = exit_date
                t["exit_reason"] = exit_reason
                t["pnl_pct"]     = round(
                    (exit_price - t["entry_price"]) / t["entry_price"] * 100, 2
                )
                t["days_held"]   = days_held
                closed_trade     = t
            else:
                remaining.append(t)

        self.save_open(remaining)

        if closed_trade:
            closed = _load(self.closed_file)
            closed.append(closed_trade)
            _save(self.closed_file, closed)
            logger.info(f"Closed trade: {trade_id} | {exit_reason} | PnL: {closed_trade['pnl_pct']}%")

        return closed_trade

    # ── Queries ───────────────────────────────────────────────

    def load_closed(self) -> List[Dict]:
        return _load(self.closed_file)

    def get_trades_closed_today(self) -> List[Dict]:
        today = date.today().isoformat()
        return [t for t in self.load_closed() if t.get("exit_date") == today]

    def summary(self) -> Dict:
        """Quick stats for Telegram EOD report."""
        open_t   = self.load_open()
        closed_t = self.load_closed()
        hits     = [t for t in closed_t if t["exit_reason"] == "TARGET_HIT"]
        expired  = [t for t in closed_t if t["exit_reason"] == "EXPIRED_30D"]
        pnls     = [t["pnl_pct"] for t in closed_t if t.get("pnl_pct") is not None]
        return {
            "open_count":    len(open_t),
            "closed_total":  len(closed_t),
            "target_hits":   len(hits),
            "expired":       len(expired),
            "win_rate_pct":  round(len(hits) / len(closed_t) * 100, 1) if closed_t else 0,
            "avg_pnl_pct":   round(sum(pnls) / len(pnls), 2) if pnls else 0,
            "best_pnl":      max(pnls, default=0),
            "worst_pnl":     min(pnls, default=0),
        }
