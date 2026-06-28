"""
kite_client.py — Thin wrapper around KiteConnect for this project.

Handles:
  • Session initialisation from env secrets
  • Historical daily candles for signal scanning
  • LTP (Last Traded Price) polling for open trade monitoring
  • Instrument token lookup by trading symbol
"""

import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import pandas_ta as ta
from kiteconnect import KiteConnect

from config import (
    KITE_API_KEY, KITE_ACCESS_TOKEN,
    ST_LENGTH, ST_MULTIPLIER,
    MIN_CANDLES, EXCHANGE
)

logger = logging.getLogger(__name__)


class KiteClient:
    def __init__(self):
        self.kite = KiteConnect(api_key=KITE_API_KEY)
        self.kite.set_access_token(KITE_ACCESS_TOKEN)
        self._instrument_map: Dict[str, int] = {}   # symbol → token
        logger.info("KiteConnect session initialised.")

    # ── Instruments ───────────────────────────────────────────

    def load_instruments(self):
        """Download full NSE instrument list and build symbol→token map."""
        instruments = self.kite.instruments(EXCHANGE)
        self._instrument_map = {
            i["tradingsymbol"]: i["instrument_token"]
            for i in instruments
            if i["instrument_type"] == "EQ"
        }
        logger.info(f"Loaded {len(self._instrument_map)} NSE EQ instruments.")

    def get_token(self, symbol: str) -> Optional[int]:
        return self._instrument_map.get(symbol)

    # ── Historical OHLC ───────────────────────────────────────

    def get_daily_candles(
        self,
        instrument_token: int,
        from_date: date,
        to_date: date
    ) -> Optional[pd.DataFrame]:
        """
        Fetch daily OHLC candles from Kite historical API.
        Returns a DataFrame with columns: Date, Open, High, Low, Close, Volume
        or None on error.
        """
        try:
            data = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date.strftime("%Y-%m-%d"),
                to_date=to_date.strftime("%Y-%m-%d"),
                interval="day",
                continuous=False,
                oi=False
            )
            if not data:
                return None

            df = pd.DataFrame(data)
            df.rename(columns={
                "date":   "Date",
                "open":   "Open",
                "high":   "High",
                "low":    "Low",
                "close":  "Close",
                "volume": "Volume"
            }, inplace=True)
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.sort_values("Date").reset_index(drop=True)
            return df

        except Exception as e:
            logger.warning(f"historical_data error for token {instrument_token}: {e}")
            return None

    # ── SuperTrend Signal Detection ───────────────────────────

    def detect_signal(
        self, symbol: str, instrument_token: int
    ) -> Optional[Dict]:
        """
        Runs the ST bearish crossover strategy on today's EOD candle.

        Returns a signal dict if all conditions are met, else None.

        Conditions:
          C1: ST(length, mult) crossed ABOVE today's High  (fresh bearish flip)
          C2: Yesterday's ST < Yesterday's Close           (was bullish)
          C3: Today's Open > Today's Close                 (red candle)
          C4: Day change % ≤ MIN_DAY_CHANGE_PCT            (≤ −5%)
        """
        today    = date.today()
        from_dt  = today - timedelta(days=365)          # ~1 year of history

        df = self.get_daily_candles(instrument_token, from_dt, today)
        if df is None or len(df) < MIN_CANDLES:
            return None

        # SuperTrend
        try:
            st_result = ta.supertrend(
                df["High"], df["Low"], df["Close"],
                length=ST_LENGTH, multiplier=ST_MULTIPLIER
            )
            st_col = next(
                c for c in st_result.columns
                if c.startswith("SUPERT_") and "SUPERTd" not in c
            )
        except Exception:
            return None

        df["ST"] = st_result[st_col].values
        df = df.dropna(subset=["ST"]).reset_index(drop=True)

        if len(df) < 2:
            return None

        today_row = df.iloc[-1]
        prev_row  = df.iloc[-2]

        st_today   = today_row["ST"]
        st_prev    = prev_row["ST"]
        high_today = today_row["High"]
        close_prev = prev_row["Close"]
        open_today = today_row["Open"]
        close_today= today_row["Close"]

        # Conditions
        c1 = (st_today > high_today) and (st_prev <= prev_row["High"])   # fresh flip
        c2 = st_prev < close_prev                                          # was bullish
        c3 = open_today > close_today                                      # red candle

        day_change_pct = (close_today - open_today) / open_today * 100

        c4 = day_change_pct <= -5.0

        if not (c1 and c2 and c3 and c4):
            return None

        return {
            "stock":         symbol,
            "instrument_token": instrument_token,
            "signal_date":   today.isoformat(),
            "entry_price":   round(float(close_today), 2),
            "target_price":  round(float(close_today * 1.05), 2),
            "day_change_pct":round(float(day_change_pct), 2),
            "st_value":      round(float(st_today), 2),
            "prev_st":       round(float(st_prev), 2),
            "prev_close":    round(float(close_prev), 2),
            "entry_day_ohlc": {
                "O": round(float(open_today), 2),
                "H": round(float(high_today), 2),
                "L": round(float(today_row["Low"]), 2),
                "C": round(float(close_today), 2),
            }
        }

    # ── Live LTP ──────────────────────────────────────────────

    def get_ltp(self, tokens: List[int]) -> Dict[int, float]:
        """
        Fetch Last Traded Price for a list of instrument tokens.
        Returns {token: ltp} dict.  Missing tokens are silently skipped.
        """
        if not tokens:
            return {}
        try:
            # Kite quote accepts "NSE:SYMBOL" or instrument tokens
            quote_keys = [f"{EXCHANGE}:{t}" if isinstance(t, str) else t
                          for t in tokens]
            resp = self.kite.ltp(tokens)
            return {
                int(token): resp[str(token)]["last_price"]
                for token in tokens
                if str(token) in resp
            }
        except Exception as e:
            logger.warning(f"LTP fetch error: {e}")
            return {}

    def get_quote(self, symbol: str) -> Optional[Dict]:
        """Full quote for a single symbol — used for EOD OHLC check."""
        try:
            key  = f"{EXCHANGE}:{symbol}"
            resp = self.kite.quote([key])
            q    = resp.get(key)
            if not q:
                return None
            return {
                "ltp":    q["last_price"],
                "open":   q["ohlc"]["open"],
                "high":   q["ohlc"]["high"],
                "low":    q["ohlc"]["low"],
                "close":  q["ohlc"]["close"],
            }
        except Exception as e:
            logger.warning(f"Quote error for {symbol}: {e}")
            return None

    # ── Nifty 500 universe ────────────────────────────────────

    def nifty500_symbols(self) -> List[str]:
        """
        Returns list of Nifty 500 trading symbols.
        We keep a static list embedded here; update periodically.
        In production you could also read from a CSV.
        """
        # Abbreviated list — replace with full 500 symbols or load from CSV
        # fmt: off
        return [
            "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","BAJFINANCE",
            "SBILIFE","KOTAKBANK","AXISBANK","LT","ASIANPAINT","MARUTI","SUNPHARMA",
            "TITAN","ULTRACEMCO","NESTLEIND","WIPRO","ONGC","NTPC","POWERGRID",
            "TECHM","HCLTECH","GRASIM","TATAMOTORS","M&M","BAJAJFINSV","ADANIPORTS",
            "TATASTEEL","COALINDIA","JSWSTEEL","SBIN","INDUSINDBK","BRITANNIA",
            "CIPLA","DIVISLAB","DRREDDY","EICHERMOT","APOLLOHOSP","TATACONSUM",
            "HEROMOTOCO","BPCL","IOC","HINDALCO","ADANIENT","VEDL","DABUR","PIDILITIND",
            "HAVELLS","BERGEPAINT","MUTHOOTFIN","SHREECEM","AMBUJACEM","ACC",
            "COLPAL","MARICO","GODREJCP","TORNTPHARM","BIOCON","LUPIN","AUROPHARMA",
            "BALKRISIND","CUMMINSIND","SIEMENS","BOSCHLTD","ABBOTINDIA","PGHH",
            "TATAPOWER","ADANIGREEN","ADANITRANS","ADANIGAS","IRCTC","ZOMATO",
            "NYKAA","POLICYBZR","PAYTM","DELHIVERY","CARTRADE","PB_FINTECH",
            "ICICIGI","HDFCLIFE","SBICARD","CHOLAFIN","BAJAJHLDNG","MOTHERSON",
            "EXIDEIND","AMARAJABAT","BATAINDIA","RAJESHEXPO","KANSAINER","ALKEM",
            "GLAND","IPCALAB","TORNTPOWER","TATACOMM","MPHASIS","LTTS","LTIM",
            "PERSISTENT","COFORGE","ZENSARTECH","HAPPSTMNDS","ROUTE","TANLA",
            "MASTEK","SONATSOFTW","INTELLECT","KPITTECH","TATAELXSI","CYIENT",
            # … add remaining Nifty 500 symbols …
        ]
        # fmt: on
