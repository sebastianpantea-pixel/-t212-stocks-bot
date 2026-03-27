import os
import time
import threading
import base64
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
T212_KEY    = os.environ.get("T212_API_KEY", "")
T212_SECRET = os.environ.get("T212_API_SECRET", "")
T212_DEMO   = os.environ.get("T212_DEMO", "true").lower() == "true"
T212_BASE   = (
    "https://demo.trading212.com/api/v0"
    if T212_DEMO
    else "https://live.trading212.com/api/v0"
)

ALPACA_KEY    = os.environ.get("ALPACA_KEY_ID", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_DATA   = "https://data.alpaca.markets"
ALPACA_CLOCK  = "https://paper-api.alpaca.markets/v2/clock"

US_SYMBOLS = {
    "AAPL", "NVDA", "MSFT", "SPY", "QQQ",
    "TSLA", "AMZN", "META", "GOOGL", "JPM",
    "AMD", "NFLX", "PLTR", "AVGO", "INTC",
    "CRM", "ORCL", "ADBE", "BAC", "XOM",
    "COST", "WMT", "MU", "SHOP", "UBER",
    "PANW", "SNOW", "AMAT", "LRCX", "GE",
    "V", "MA", "KO", "PEP", "DIS"
}

DEFAULT_SYMBOLS = ["AAPL", "NVDA", "MSFT", "SPY", "QQQ",
                   "TSLA", "AMZN", "META", "GOOGL", "JPM"]

# ──────────────────────────────────────────────────────────────────────────────
# State
# ──────────────────────────────────────────────────────────────────────────────
state = {
    "running":    False,
    "balance":    0.0,
    "pnl":        0.0,
    "daily_dd":   0.0,
    "wins":       0,
    "losses":     0,
    "positions":  [],
    "history":    [],
    "log":        [],
    "scan_count": 0,
    "last_scan":  None,
    "market":     "closed",
    "regime":     "unknown",
}

settings = {
    "symbols":       DEFAULT_SYMBOLS.copy(),
    "risk_pct":      1.0,
    "dd_limit":      5.0,
    "sl_pct":        1.5,
    "rr_ratio":      3.0,
    "max_positions": 3,
    "scan_interval": 300,
}

bot_thread    = None
start_balance = 0.0
t212_lock     = threading.Lock()
t212_last_call = {}
t212_cache    = {}

T212_RATE_LIMITS = {
    "/equity/account/summary": 5.2,
    "/equity/portfolio":       1.2,
    "/equity/orders":          5.2,
    "/equity/orders/market":   1.2,
}

T212_CACHE_TTL = {
    "/equity/account/summary": 15.0,
    "/equity/portfolio":        3.0,
    "/equity/orders":           5.0,
}

t212_session  = requests.Session()
alpaca_session = requests.Session()

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
def add_log(msg, level="info"):
    entry = {
        "time":  datetime.utcnow().strftime("%H:%M:%S"),
        "msg":   str(msg),
        "level": level,
    }
    state["log"].insert(0, entry)
    if len(state["log"]) > 300:
        state["log"] = state["log"][:300]
    print(f"[{entry['time']}] [{level.upper()}] {msg}")

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def safe_float(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except Exception:
        return default

def safe_int(v, default=0):
    try:
        return int(v) if v is not None else default
    except Exception:
        return default

# ──────────────────────────────────────────────────────────────────────────────
# T212 API
# ──────────────────────────────────────────────────────────────────────────────
def t212_headers():
    creds = base64.b64encode(f"{T212_KEY}:{T212_SECRET}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}

def _t212_wait(endpoint):
    min_wait = T212_RATE_LIMITS.get(endpoint, 1.0)
    since = time.time() - t212_last_call.get(endpoint, 0.0)
    if since < min_wait:
        time.sleep(min_wait - since)

def _get_cache(endpoint):
    ttl = T212_CACHE_TTL.get(endpoint)
    if not ttl:
        return None
    cached = t212_cache.get(endpoint)
    if cached and time.time() - cached["ts"] <= ttl:
        return cached["data"]
    return None

def _set_cache(endpoint, data):
    if endpoint in T212_CACHE_TTL:
        t212_cache[endpoint] = {"ts": time.time(), "data": data}

def _invalidate_cache(*endpoints):
    for ep in endpoints:
        t212_cache.pop(ep, None)

def t212_get(endpoint, use_cache=True):
    with t212_lock:
        if use_cache:
            cached = _get_cache(endpoint)
            if cached is not None:
                return cached
        for attempt in range(3):
            try:
                _t212_wait(endpoint)
                r = t212_session.get(
                    f"{T212_BASE}{endpoint}",
                    headers=t212_headers(), timeout=10)
                t212_last_call[endpoint] = time.time()
                if r.status_code == 429:
                    wait = safe_float(r.headers.get("Retry-After"), 6.0)
                    add_log(f"T212 429 {endpoint}, astept {wait:.0f}s", "warn")
                    if attempt < 2:
                        time.sleep(wait)
                        continue
                    return None
                r.raise_for_status()
                data = r.json()
                _set_cache(endpoint, data)
                return data
            except Exception as e:
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                else:
                    add_log(f"T212 GET {endpoint}: {e}", "err")
        return None

def t212_post(endpoint, body):
    with t212_lock:
        for attempt in range(2):
            try:
                _t212_wait(endpoint)
                r = t212_session.post(
                    f"{T212_BASE}{endpoint}",
                    headers=t212_headers(), json=body, timeout=10)
                t212_last_call[endpoint] = time.time()
                if r.status_code == 429:
                    wait = safe_float(r.headers.get("Retry-After"), 6.0)
                    if attempt < 1:
                        time.sleep(wait)
                        continue
                    return None
                r.raise_for_status()
                _invalidate_cache("/equity/account/summary",
                                  "/equity/portfolio", "/equity/orders")
                return r.json() if r.content else {"ok": True}
            except Exception as e:
                if attempt < 1:
                    time.sleep(2)
                else:
                    add_log(f"T212 POST {endpoint}: {e}", "err")
        return None

def get_account(force=False):
    return t212_get("/equity/account/summary", use_cache=not force)

def get_portfolio(force=False):
    return t212_get("/equity/portfolio", use_cache=not force)

# ──────────────────────────────────────────────────────────────────────────────
# Alpaca Market Data
# ──────────────────────────────────────────────────────────────────────────────
def alpaca_headers():
    return {
        "APCA-API-KEY-ID":     ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
    }

def get_price(symbol):
    if symbol not in US_SYMBOLS:
        return None, None, None
    try:
        r = alpaca_session.get(
            f"{ALPACA_DATA}/v2/stocks/{symbol}/quotes/latest",
            headers=alpaca_headers(),
            params={"feed": "iex"}, timeout=8)
        r.raise_for_status()
        quote = r.json().get("quote", {})
        ask = safe_float(quote.get("ap"), 0.0)
        bid = safe_float(quote.get("bp"), 0.0)
        if ask > 0 and bid > 0:
            return (ask + bid) / 2.0, bid, ask
        if ask > 0:
            return ask, ask, ask
        if bid > 0:
            return bid, bid, bid
        return None, None, None
    except Exception as e:
        add_log(f"Price {symbol}: {e}", "warn")
        return None, None, None

def get_bars(symbol, timeframe="1Hour", limit=80):
    if symbol not in US_SYMBOLS:
        add_log(f"Bars {symbol}: simbol nesupported pe Alpaca", "warn")
        return []
    # Incearca IEX mai intai, apoi fallback la SIP (delayed)
    for feed in ["iex", "sip"]:
        try:
            r = alpaca_session.get(
                f"{ALPACA_DATA}/v2/stocks/{symbol}/bars",
                headers=alpaca_headers(),
                params={"timeframe": timeframe, "limit": limit,
                        "feed": feed, "adjustment": "raw"}, timeout=10)
            r.raise_for_status()
            raw = r.json().get("bars", [])
            if raw:
                bars = [{"o": safe_float(b.get("o")), "h": safe_float(b.get("h")),
                         "l": safe_float(b.get("l")), "c": safe_float(b.get("c")),
                         "v": safe_int(b.get("v")), "t": b.get("t")} for b in raw if isinstance(b, dict)]
                if len(bars) >= 10:
                    return bars
        except Exception as e:
            add_log(f"Bars {symbol} ({feed}): {e}", "warn")
    return []

def get_market_status():
    try:
        r = alpaca_session.get(ALPACA_CLOCK, headers=alpaca_headers(), timeout=5)
        r.raise_for_status()
        is_open = bool(r.json().get("is_open", False))
        state["market"] = "open" if is_open else "closed"
        return is_open
    except Exception:
        pass
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        state["market"] = "weekend"
        return False
    h = now.hour + now.minute / 60.0
    is_open = 13.5 <= h < 20.0
    state["market"] = "open" if is_open else "closed"
    return is_open

# ──────────────────────────────────────────────────────────────────────────────
# Indicatori
# ──────────────────────────────────────────────────────────────────────────────
def calc_ema(closes, n):
    if not closes or len(closes) < n:
        return None
    k = 2 / (n + 1)
    e = closes[0]
    for c in closes[1:]:
        e = c * k + e * (1 - k)
    return e

def calc_rsi(bars, period=14):
    if len(bars) < period + 2:
        return None
    closes = [b["c"] for b in bars[-(period + 2):]]
    gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)

def calc_atr(bars, n=14):
    if len(bars) < n + 1:
        return None
    trs = [max(bars[i]["h"] - bars[i]["l"],
               abs(bars[i]["h"] - bars[i-1]["c"]),
               abs(bars[i]["l"] - bars[i-1]["c"]))
           for i in range(1, len(bars))]
    return sum(trs[-n:]) / n if len(trs) >= n else None

def detect_regime(bars):
    if len(bars) < 30:
        return "unknown"
    atr_now = calc_atr(bars[-15:], 14)
    atr_old = calc_atr(bars[-30:-14], 14)
    if not atr_now or not atr_old or atr_old == 0:
        return "unknown"
    return "trending" if atr_now > atr_old * 1.2 else "ranging"

# ──────────────────────────────────────────────────────────────────────────────
# Strategie relaxata — Triple EMA + RSI + Momentum
# ──────────────────────────────────────────────────────────────────────────────
def scan_symbol(symbol):
    """
    Strategie multi-confirmare relaxata:
    - EMA trend pe 1H (EMA20 vs EMA50)
    - Momentum: 2 candele consecutive in directia trendului
    - RSI: nu in zona opusa (nu cumpar in supracumparare)
    - Returneaza (direction, reason) sau None
    """
    bars = get_bars(symbol, "1Hour", 60)

    if len(bars) < 15:
        add_log(f"{symbol}: date insuficiente ({len(bars)} bare)", "warn")
        return None

    closes = [b["c"] for b in bars]
    ema20  = calc_ema(closes[-20:], 20)
    n50   = min(50, len(closes))
    ema50  = calc_ema(closes[-n50:], n50)
    rsi    = calc_rsi(bars, 14)
    regime = detect_regime(bars)
    state["regime"] = regime

    if not ema20 or not ema50:
        return None

    price     = closes[-1]
    prev      = closes[-2]
    prev2     = closes[-3]

    # Trend direction
    bullish_trend = ema20 > ema50 and price > ema20
    bearish_trend = ema20 < ema50 and price < ema20

    # Momentum: 2 bare consecutive green/red
    bull_mom = bars[-1]["c"] > bars[-1]["o"] and bars[-2]["c"] > bars[-2]["o"]
    bear_mom = bars[-1]["c"] < bars[-1]["o"] and bars[-2]["c"] < bars[-2]["o"]

    # RSI filter
    rsi_ok_long  = rsi is None or rsi < 70   # nu cumpar in supracumparare
    rsi_ok_short = rsi is None or rsi > 30   # nu vand in supravanzare

    # Pullback simplu: pretul a atins EMA20 in ultimele 3 bare
    recent_lows  = [b["l"] for b in bars[-4:-1]]
    recent_highs = [b["h"] for b in bars[-4:-1]]
    touched_ema_low  = any(l <= ema20 * 1.003 for l in recent_lows)
    touched_ema_high = any(h >= ema20 * 0.997 for h in recent_highs)

    add_log(f"{symbol} | EMA20:{ema20:.2f} EMA50:{ema50:.2f} | RSI:{rsi:.1f if rsi else '—'} | {regime}", "info")

    # LONG: trend bullish + momentum + RSI ok + pullback la EMA
    if bullish_trend and bull_mom and rsi_ok_long and touched_ema_low:
        return ("LONG", f"EMA trend + momentum + pullback | RSI:{rsi:.0f if rsi else '—'}")

    # SHORT: trend bearish + momentum + RSI ok + pullback la EMA
    if bearish_trend and bear_mom and rsi_ok_short and touched_ema_high:
        return ("SHORT", f"EMA trend + momentum + pullback | RSI:{rsi:.0f if rsi else '—'}")

    # Fallback mai relaxat — doar trend + momentum (fara pullback obligatoriu)
    if bullish_trend and bull_mom and rsi_ok_long and price > prev and prev > prev2:
        return ("LONG", f"EMA trend + 3 bare bullish | RSI:{rsi:.0f if rsi else '—'}")

    if bearish_trend and bear_mom and rsi_ok_short and price < prev and prev < prev2:
        return ("SHORT", f"EMA trend + 3 bare bearish | RSI:{rsi:.0f if rsi else '—'}")

    return None

# ──────────────────────────────────────────────────────────────────────────────
# Executie
# ──────────────────────────────────────────────────────────────────────────────
def open_trade(symbol, direction, reason):
    mid, bid, ask = get_price(symbol)
    if not mid:
        add_log(f"Nu am pret pentru {symbol}", "err")
        return

    price    = ask if direction == "LONG" else bid
    balance  = state["balance"]
    risk_usd = balance * (settings["risk_pct"] / 100.0)
    sl_pct   = settings["sl_pct"] / 100.0
    tp_pct   = sl_pct * settings["rr_ratio"]

    sl = price * (1 - sl_pct) if direction == "LONG" else price * (1 + sl_pct)
    tp = price * (1 + tp_pct) if direction == "LONG" else price * (1 - tp_pct)

    sl_dist = abs(price - sl)
    if sl_dist <= 0:
        return

    shares = round(min(risk_usd / sl_dist, balance * 0.4 / price), 2)
    if shares <= 0:
        add_log(f"Size invalid {symbol}: {shares}", "err")
        return

    qty    = shares if direction == "LONG" else -shares
    ticker = f"{symbol}_US_EQ"

    result = t212_post("/equity/orders/market", {"ticker": ticker, "quantity": qty})

    if not result or "id" not in result:
        add_log(f"Ordin respins {symbol}: {result}", "err")
        return

    state["positions"].append({
        "id":         str(result["id"]),
        "symbol":     symbol,
        "ticker":     ticker,
        "direction":  direction,
        "entry":      round(price, 4),
        "mark_price": round(price, 4),
        "sl":         round(sl, 4),
        "tp":         round(tp, 4),
        "shares":     shares,
        "pnl_live":   0.0,
        "status":     "open",
        "open_time":  datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "reason":     reason,
    })
    add_log(f"✅ {direction} {symbol} @ ${price:.2f} | SL:${sl:.2f} TP:${tp:.2f} | {shares}sh | {reason}", "ok")

def close_trade(pos, reason):
    mid, bid, ask = get_price(pos["symbol"])
    exit_price    = mid or pos.get("mark_price") or pos["entry"]
    qty    = -pos["shares"] if pos["direction"] == "LONG" else pos["shares"]
    result = t212_post("/equity/orders/market", {"ticker": pos["ticker"], "quantity": qty})

    if not result or "id" not in result:
        add_log(f"Eroare inchidere {pos['symbol']}: {result}", "err")
        return

    pnl = ((exit_price - pos["entry"]) * pos["shares"]
           if pos["direction"] == "LONG"
           else (pos["entry"] - exit_price) * pos["shares"])

    pos.update({
        "status":     "closed",
        "close_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "mark_price": round(exit_price, 4),
        "pnl_live":   round(pnl, 2),
    })
    state["pnl"] += pnl

    if pnl > 0:
        state["wins"] += 1
    else:
        state["losses"]   += 1
        state["daily_dd"] += abs(pnl) / max(state["balance"], 1) * 100.0

    sl_dist = abs(pos["entry"] - pos["sl"])
    rr_val  = abs((exit_price - pos["entry"]) / sl_dist) if sl_dist > 0 else 0
    rr      = f"1:{rr_val:.1f}"

    state["history"].append({
        "date":   datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "symbol": pos["symbol"],
        "dir":    pos["direction"],
        "entry":  pos["entry"],
        "exit":   round(exit_price, 4),
        "shares": pos["shares"],
        "pnl":    round(pnl, 2),
        "rr":     rr,
        "reason": reason,
    })
    add_log(f"{'✅' if pnl > 0 else '❌'} {pos['symbol']} {reason} | ${pnl:+.2f} | {rr}",
            "ok" if pnl > 0 else "err")

    if state["daily_dd"] >= settings["dd_limit"]:
        add_log(f"Daily DD {state['daily_dd']:.2f}% atins. Bot oprit.", "err")
        state["running"] = False

def sync_positions():
    portfolio = get_portfolio()
    if not portfolio:
        return

    pmap = {}
    items = portfolio if isinstance(portfolio, list) else portfolio.get("items", [])
    for p in items:
        if isinstance(p, dict):
            pmap[p.get("ticker", "")] = p

    for pos in state["positions"]:
        if pos.get("status") != "open":
            continue
        live = pmap.get(pos["ticker"])
        if not live:
            continue
        price = safe_float(live.get("currentPrice"), pos["entry"])
        pos["mark_price"] = price
        pos["pnl_live"]   = safe_float(live.get("ppl"), 0.0)

        hit_tp = (pos["direction"] == "LONG"  and price >= pos["tp"]) or \
                 (pos["direction"] == "SHORT" and price <= pos["tp"])
        hit_sl = (pos["direction"] == "LONG"  and price <= pos["sl"]) or \
                 (pos["direction"] == "SHORT" and price >= pos["sl"])

        if hit_tp:
            add_log(f"🎯 TP atins {pos['symbol']} @ ${price:.2f}", "warn")
            close_trade(pos, "TP hit")
        elif hit_sl:
            add_log(f"🛑 SL atins {pos['symbol']} @ ${price:.2f}", "warn")
            close_trade(pos, "SL hit")

# ──────────────────────────────────────────────────────────────────────────────
# Bot loop
# ──────────────────────────────────────────────────────────────────────────────
def refresh_balance(force=False):
    global start_balance
    acc = get_account(force=force)
    if not acc:
        return False
    cash = acc.get("cash", {}) if isinstance(acc, dict) else {}
    bal  = safe_float(cash.get("availableToTrade"), 0.0)
    if bal <= 0:
        bal = safe_float(acc.get("totalValue"), state["balance"])
    if bal > 0:
        state["balance"] = bal
        if start_balance <= 0:
            start_balance = bal
        return True
    return False

def bot_loop():
    global start_balance
    add_log("🟢 Bot T212 Stocks pornit.", "ok")

    if not refresh_balance(force=True):
        add_log("Nu pot obtine balanta T212 — verifica API keys.", "err")
        state["running"] = False
        return

    add_log(f"Balanta T212: ${state['balance']:,.2f}", "ok")
    add_log(f"Simboluri: {', '.join(settings['symbols'])}", "info")

    last_bal_refresh = 0.0

    while state["running"]:
        try:
            state["scan_count"] += 1
            state["last_scan"]   = datetime.utcnow().strftime("%H:%M:%S")

            sync_positions()

            if time.time() - last_bal_refresh >= 30:
                refresh_balance()
                last_bal_refresh = time.time()

            is_open = get_market_status()
            add_log(f"Scan #{state['scan_count']} | Piata: {'DESCHISA' if is_open else 'INCHISA'}")

            if not is_open:
                add_log("Piata inchisa — astept NYSE open.", "warn")
            else:
                open_count = len([p for p in state["positions"] if p.get("status") == "open"])

                if open_count >= settings["max_positions"]:
                    add_log(f"Max {settings['max_positions']} pozitii. Astept exit.", "warn")
                else:
                    for symbol in settings["symbols"]:
                        if not state["running"]:
                            break
                        if any(p.get("status") == "open" and p.get("symbol") == symbol
                               for p in state["positions"]):
                            continue

                        add_log(f"Scanez {symbol}...", "info")
                        try:
                            sig = scan_symbol(symbol)
                        except Exception as e:
                            add_log(f"Scan {symbol}: {e}", "err")
                            continue

                        if sig:
                            direction, reason = sig
                            add_log(f"📊 {symbol}: {direction} — {reason}", "warn")
                            open_trade(symbol, direction, reason)
                            open_count += 1
                            if open_count >= settings["max_positions"]:
                                break

                        time.sleep(1.5)

        except Exception as e:
            add_log(f"Eroare bot_loop: {e}", "err")

        interval = max(safe_int(settings.get("scan_interval", 300)), 5)
        for _ in range(interval):
            if not state["running"]:
                break
            time.sleep(1)

    add_log("Bot oprit.", "warn")

# ──────────────────────────────────────────────────────────────────────────────
# API
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/status")
def api_status():
    total    = state["wins"] + state["losses"]
    open_pos = [p for p in state["positions"] if p.get("status") == "open"]
    live_pnl = sum(p.get("pnl_live", 0) for p in open_pos)
    return jsonify({
        "running":          state["running"],
        "demo":             T212_DEMO,
        "balance":          round(state["balance"], 2),
        "pnl":              round(state["pnl"], 2),
        "live_pnl":         round(live_pnl, 2),
        "pnl_pct":          round(state["pnl"] / max(start_balance, 1) * 100, 2),
        "daily_dd":         round(state["daily_dd"], 2),
        "wins":             state["wins"],
        "losses":           state["losses"],
        "win_rate":         round(state["wins"] / total * 100, 1) if total > 0 else 0,
        "active_positions": len(open_pos),
        "scan_count":       state["scan_count"],
        "last_scan":        state["last_scan"],
        "market":           state["market"],
        "regime":           state["regime"],
        "settings":         settings,
    })

@app.route("/api/positions")
def api_positions():
    return jsonify(state["positions"])

@app.route("/api/history")
def api_history():
    return jsonify(list(reversed(state["history"][-50:])))

@app.route("/api/log")
def api_log():
    return jsonify(state["log"][:100])

@app.route("/api/start", methods=["POST"])
def api_start():
    global bot_thread
    if state["running"]:
        return jsonify({"ok": False, "msg": "Bot deja pornit"})
    if not T212_KEY or not T212_SECRET:
        return jsonify({"ok": False, "msg": "T212_API_KEY sau T212_API_SECRET lipsa"})
    if not ALPACA_KEY or not ALPACA_SECRET:
        return jsonify({"ok": False, "msg": "ALPACA_KEY_ID sau ALPACA_SECRET_KEY lipsa"})
    state["running"]  = True
    state["daily_dd"] = 0.0
    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()
    return jsonify({"ok": True})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    state["running"] = False
    return jsonify({"ok": True})

@app.route("/api/settings", methods=["POST"])
def api_settings():
    data = request.get_json() or {}
    if "symbols" in data:
        syms = [s.strip().upper() for s in data["symbols"] if s]
        settings["symbols"] = [s for s in syms if s in US_SYMBOLS] or DEFAULT_SYMBOLS.copy()
    for k, cast in [("risk_pct", float), ("dd_limit", float), ("sl_pct", float),
                    ("rr_ratio", float), ("max_positions", int), ("scan_interval", int)]:
        if k in data:
            try:
                settings[k] = cast(data[k])
            except Exception:
                pass
    add_log(f"Setari actualizate: {settings['symbols']}", "info")
    return jsonify({"ok": True, "settings": settings})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
