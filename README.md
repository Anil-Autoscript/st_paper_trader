# ST Paper Trader 🔴
### SuperTrend(80,15) Bearish Crossover | Daily EOD Strategy | Paper Trading

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  GitHub Actions (Cron)          Render.com (Always-On Worker)   │
│                                                                  │
│  08:00 IST ──► kite_login.py   │  live_monitor.py              │
│  (refresh access token)         │  ↕ polls LTP every 60s        │
│                                 │  ↕ during 09:15–15:30 IST     │
│  15:35 IST ──► eod_scanner.py  │  ↕ checks open trades         │
│  (detect new signals,           │  → TARGET HIT → Telegram 🔔   │
│   check 30-day expiries,        │                                │
│   send EOD Telegram report)     │                                │
│                                 │                                │
│           Both read/write       data/open_trades.json            │
│                                 data/closed_trades.json          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Strategy Rules

| Rule | Condition |
|------|-----------|
| **C1** | ST(80,15) crossed **above** today's High (fresh bearish flip) |
| **C2** | Yesterday's ST < Yesterday's Close (was bullish) |
| **C3** | Today's Open > Today's Close (red candle) |
| **C4** | Day Change % **≤ −5%** |
| **Entry** | Signal day **Close** price |
| **Target** | Entry × 1.05 (+5%) |
| **Exit** | Target hit (via LTP polling) OR 30-day timeout (EOD close) |

---

## File Structure

```
st_paper_trader/
├── src/
│   ├── config.py          # All tuneable parameters
│   ├── kite_client.py     # Kite API wrapper (OHLC, LTP, instruments)
│   ├── trade_store.py     # JSON persistence (open + closed trades)
│   ├── telegram.py        # Telegram Bot notifications
│   ├── eod_scanner.py     # GitHub Actions EOD runner
│   ├── live_monitor.py    # Render persistent LTP monitor
│   └── kite_login.py      # Daily access token refresher
├── data/                  # Auto-created; JSON trade files live here
│   ├── open_trades.json
│   └── closed_trades.json
├── .github/workflows/
│   ├── eod_scanner.yml    # Cron: 15:35 IST weekdays
│   └── kite_login.yml     # Cron: 08:00 IST weekdays
├── render.yaml            # Render Blueprint for live_monitor
├── requirements.txt
└── README.md
```

---

## Step-by-Step Setup

### 1. Kite Connect App
1. Go to [kite.trade/developers](https://kite.trade/developers)
2. Create a new app → note `api_key` and `api_secret`
3. Set **Redirect URL** to any HTTPS URL you control (e.g. `https://yourdomain.com/callback`)
4. Enable **Historical Data** add-on (₹2000/month) — required for candle data

### 2. Telegram Bot
1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → note the `bot_token`
2. Start your bot, then fetch your `chat_id`:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   Look for `"chat": {"id": YOUR_CHAT_ID}`

### 3. GitHub Repository Secrets
Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Value |
|-------------|-------|
| `KITE_API_KEY` | Your Kite app API key |
| `KITE_API_SECRET` | Your Kite app API secret |
| `KITE_USER_ID` | Your Zerodha user ID (e.g. `AB1234`) |
| `KITE_PASSWORD` | Your Zerodha login password |
| `KITE_TOTP_SECRET` | **Optional** — your TOTP base32 secret (enables full auto-login) |
| `KITE_ACCESS_TOKEN` | Initially empty; auto-updated by `kite_login.py` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `GH_PAT` | GitHub Personal Access Token with `secrets` write scope |

### 4. Get your TOTP Secret (Recommended — enables full automation)
1. In Zerodha app → Profile → Settings → Two-factor auth
2. When setting up TOTP, they show a QR code + a base32 secret string
3. Copy the **base32 secret** → add as `KITE_TOTP_SECRET` GitHub secret
4. With this set, `kite_login.py` logs in fully automatically every morning

### 5. GitHub Personal Access Token (for secret auto-update)
1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained
2. Scope: **Repository secrets** (read and write)
3. Add as `GH_PAT` secret

### 6. Deploy Live Monitor on Render
1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → New → **Blueprint**
3. Connect your GitHub repo → Render reads `render.yaml`
4. In Render dashboard → Environment → add all 4 env vars:
   - `KITE_API_KEY`
   - `KITE_ACCESS_TOKEN`  ← update this manually for first run; auto after
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. **Important:** Use **Starter plan ($7/month)** — free plan sleeps after 15 min

> **Note on Render + access token:** The live_monitor reads `KITE_ACCESS_TOKEN`
> from its environment at startup. After `kite_login.py` updates the GitHub secret,
> you also need to update it in Render. To automate this, add a Render Deploy Hook
> or use Render's API in `kite_login.py` (extend the `update_github_secret` function).

### 7. Nifty 500 Stock List
Edit `kite_client.py` → `nifty500_symbols()` and replace the abbreviated list
with all 500 symbols. You can get the full list from:
- [NSE India](https://www.nseindia.com/market-data/equity-market-cap/nifty500)
- Export the CSV and parse the `Symbol` column

---

## Daily Flow

```
08:00 IST  GitHub Actions → kite_login.yml
           → Generates Kite session (TOTP auto or manual OTP)
           → Updates KITE_ACCESS_TOKEN GitHub secret
           → Sends "Login Successful 🟢" to Telegram

09:15 IST  Render live_monitor.py wakes from sleep loop
           → Starts polling LTP every 60 seconds for all open trades
           → If any trade's LTP ≥ target_price → logs exit + Telegram alert

15:30 IST  Market closes → live_monitor enters sleep loop

15:35 IST  GitHub Actions → eod_scanner.yml
           → Scans Nifty 500 for new ST bearish crossover signals
           → Filters: Day Change % ≤ −5%
           → Adds new signals to open_trades.json
           → Checks open trades ≥ 30 days → closes at EOD close
           → Sends full EOD Telegram report
```

---

## Telegram Reports

### New Signal Alert (immediate, when detected)
```
🔴 NEW SIGNAL — ST BEARISH CROSSOVER
━━━━━━━━━━━━━━━━━━━━━
📌 Stock     : RELIANCE
📅 Date      : 10-Jun-2024
Entry (Signal Close)  : ₹2850.00
🎯 Target (+5%)       : ₹2992.50
Day Change %          : -6.23%
...
```

### Target Hit Alert (intraday, immediate)
```
✅ TARGET HIT — PAPER EXIT
━━━━━━━━━━━━━━━━━━━━━
📌 Stock      : RELIANCE
Entry Price : ₹2850.00
Exit LTP    : ₹2993.10
📈 P&L       : +5.02%  🎉
Days Held   : 7d
```

### EOD Report (15:35 IST daily)
```
📊 EOD REPORT — 10-Jun-2024
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 NEW SIGNALS TODAY  (3)
  • RELIANCE       Entry ₹2850.00  Day% -6.23%  → Target ₹2992.50
  ...

📂 OPEN TRADES  (8)
  • HDFCBANK       Entry ₹1620.00  Tgt ₹1701.00  LTP ₹1650.00  Unr +1.85%  Day 12/30
  ...

✅ CLOSED TODAY  (1)
  🟢 TCS            Entry ₹3800.00 → Exit ₹3990.00  +5.00%  [TARGET_HIT]  5d

📈 OVERALL STATS
  Total Closed   : 24
  Target Hits    : 18  |  Expired: 6
  Win Rate       : 75.0%
  Avg P&L        : +3.12%
```

---

## Configuration (src/config.py)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ST_LENGTH` | 80 | SuperTrend ATR length |
| `ST_MULTIPLIER` | 15 | SuperTrend multiplier |
| `MIN_DAY_CHANGE_PCT` | -5.0 | Signal filter threshold |
| `PROFIT_TARGET_PCT` | 5.0 | Exit target % |
| `MAX_HOLD_DAYS` | 30 | Force exit after N days |
| `POLL_INTERVAL_SEC` | 60 | LTP polling frequency (Render) |

---

## Troubleshooting

**"Instrument token not found"**
→ Run `kite.load_instruments()` and verify the symbol exists in NSE EQ segment.
→ Some symbols differ (e.g. `M&M` vs `MM`). Check Kite's tradingsymbol exactly.

**"historical_data error"**
→ Ensure your Kite account has the **Historical Data API add-on** enabled.

**Access token expired mid-day**
→ Tokens expire at midnight IST. The 08:00 IST login workflow covers this.
→ If the Render service restarts mid-day, update `KITE_ACCESS_TOKEN` in Render env.

**GitHub Actions cache miss (trade data lost)**
→ Trade data is cached between runs. Cache keys use run_id for saving but
   restore from any previous `trade-data-ubuntu-*` key. This should be robust.
→ For production, consider committing the JSON files or using a small DB.
