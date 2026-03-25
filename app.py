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
T212_KEY = os.environ.get("T212_API_KEY", "")
T212_SECRET = os.environ.get("T212_API_SECRET", "")
T212_DEMO = os.environ.get("T212_DEMO", "true").lower() == "true"
T212_BASE = (
    "https://demo.trading212.com/api/v0"
    if T212_DEMO
    else "https://live.trading212.com/api/v0"
)

ALPACA_KEY = os.environ.get("ALPACA_KEY_ID", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_DATA = "https://data.alpaca.markets"
ALPACA_CLOCK = "https://paper-api.alpaca.markets/v2/clock"

# Simboluri default, curate, potrivite pentru bot
SUPPORTED_DEFAULT_SYMBOLS = [
    "AAPL", "NVDA", "MSFT", "SPY", "QQQ",
    "TSLA", "AMZN", "META", "GOOGL", "JPM"
]

# Lista mai larga de simboluri pe care le permiti in bot
ALLOWED_SYMBOLS = {
    "AAPL", "NVDA", "MSFT", "SPY", "QQQ",
    "TSLA", "AMZN", "META", "GOOGL", "JPM",
    "AMD", "NFLX", "PLTR", "AVGO", "INTC",
    "CRM", "ORCL", "ADBE", "BAC", "XOM",
    "COST", "WMT", "MU", "SHOP", "UBER",
    "PANW", "SNOW", "AMAT", "LRCX", "GE",
    "V", "MA", "KO", "PEP", "DIS"
}

# Lista preferata pentru regim 24/5, adica ce vrei sa prioritizezi
PREFERRED_24_5_SYMBOLS = {
    "AAPL", "NVDA", "MSFT", "SPY", "QQQ",
    "TSLA", "AMZN", "META", "GOOGL", "JPM",
    "AMD", "NFLX", "PLTR", "AVGO"
}

# Daca True, botul accepta doar simboluri din lista preferata 24/5
ONLY_PREFERRED_24_5 = os.environ.get("ONLY_PREFERRED_24_5", "true").lower() == "true"

# ──────────────────────────────────────────────────────────────────────────────
# State
# ──────────────────────────────────────────────────────────────────────────────
state = {
    "running": False,
    "balance": 0.0,
    "pnl": 0.0,
    "daily_dd": 0.0,
    "wins": 0,
    "losses": 0,
    "positions": [],
    "history": [],
    "log": [],
    "scan_count": 0,
    "last_scan": None,
    "market": "closed",
    "regime": "unknown",
    "symbol_mode": "preferred_24_5" if ONLY_PREFERRED_24_5 else "allowed",
}

settings = {
    "symbols": SUPPORTED_DEFAULT_SYMBOLS.copy(),
    "risk_pct": 1.0,
    "dd_limit": 5.0,
    "sl_pct": 1.5,
    "rr_ratio": 3.0,
    "max_positions": 3,
    "scan_interval": 300,
    "only_preferred_24_5": ONLY_PREFERRED_24_5,
}

bot_thread = None
start_balance = 0.0

# ──────────────────────────────────────────────────────────────────────────────
# Sessions
# ──────────────────────────────────────────────────────────────────────────────
t212_session = requests.Session()
alpaca_session = requests.Session()

# ──────────────────────────────────────────────────────────────────────────────
# Rate limit / cache Trading 212
# ──────────────────────────────────────────────────────────────────────────────
t212_lock = threading.Lock()

T212_RATE_LIMITS = {
    "/equity/account/summary": 5.2,
    "/equity/portfolio": 1.2,
    "/equity/orders": 5.2,
    "/equity/orders/market": 1.2,
}

t212_last_call = {}
t212_cache = {}

T212_CACHE_TTL = {
    "/equity/account/summary": 15.0,
    "/equity/portfolio": 3.0,
    "/equity/orders": 5.0,
}

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
def add_log(msg, level="info"):
    entry = {
        "time": datetime.utcnow().strftime("%H:%M:%S"),
        "msg": str(msg),
        "level": level,
    }
    state["log"].insert(0, entry)
    if len(state["log"]) > 300:
        state["log"] = state["log"][:300]
    print(f"[{entry['time']}] [{level.upper()}] {msg}")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def clean_closed_positions():
    if len(state["positions"]) <= 200:
        return

    open_positions = [p for p in state["positions"] if p.get("status") == "open"]
    closed_positions = [p for p in state["positions"] if p.get("status") != "open"]
    closed_positions = closed_positions[-150:]
    state["positions"] = open_positions + closed_positions


def get_symbol_universe(preferred_only=None):
    if preferred_only is None:
        preferred_only = bool(settings.get("only_preferred_24_5", ONLY_PREFERRED_24_5))
    return PREFERRED_24_5_SYMBOLS if preferred_only else ALLOWED_SYMBOLS


def filter_tradeable_symbols(symbols, preferred_only=None):
    universe = get_symbol_universe(preferred_only)

    if not isinstance(symbols, list):
        fallback = [s for s in SUPPORTED_DEFAULT_SYMBOLS if s in universe]
        return fallback if fallback else SUPPORTED_DEFAULT_SYMBOLS.copy()

    valid = []
    blocked = []

    for raw in symbols:
        sym = str(raw or "").strip().upper()
        if not sym:
            continue

        if sym in universe:
            if sym not in valid:
                valid.append(sym)
        else:
            blocked.append(sym)

    if blocked:
        mode_label = "preferred 24/5" if (preferred_only if preferred_only is not None else settings.get("only_preferred_24_5", ONLY_PREFERRED_24_5)) else "allowed"
        add_log(f"Simboluri respinse ({mode_label}): {', '.join(blocked)}", "warn")

    if valid:
        return valid[:30]

    fallback = [s for s in SUPPORTED_DEFAULT_SYMBOLS if s in universe]
    return fallback if fallback else SUPPORTED_DEFAULT_SYMBOLS.copy()


def normalize_symbols(raw_symbols, preferred_only=None):
    if not isinstance(raw_symbols, list):
        return filter_tradeable_symbols(SUPPORTED_DEFAULT_SYMBOLS.copy(), preferred_only)

    cleaned = []
    for s in raw_symbols:
        if s is None:
            continue
        sym = str(s).strip().upper()
        if not sym:
            continue
        cleaned.append(sym)

    seen = set()
    deduped = []
    for s in cleaned:
        if s not in seen:
            seen.add(s)
            deduped.append(s)

    return filter_tradeable_symbols(deduped[:30], preferred_only)


# ──────────────────────────────────────────────────────────────────────────────
# Trading 212 API
# ──────────────────────────────────────────────────────────────────────────────
def t212_headers():
    creds = base64.b64encode(f"{T212_KEY}:{T212_SECRET}".encode()).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/json",
    }


def _t212_wait_for_rate_limit(endpoint):
    min_wait = T212_RATE_LIMITS.get(endpoint, 1.0)
    now = time.time()
    last = t212_last_call.get(endpoint, 0.0)
    wait_s = min_wait - (now - last)
    if wait_s > 0:
        time.sleep(wait_s)


def _t212_get_cache(endpoint):
    ttl = T212_CACHE_TTL.get(endpoint)
    if ttl is None:
        return None

    cached = t212_cache.get(endpoint)
    if not cached:
        return None

    age = time.time() - cached["ts"]
    if age <= ttl:
        return cached["data"]

    return None


def _t212_set_cache(endpoint, data):
    if endpoint in T212_CACHE_TTL:
        t212_cache[endpoint] = {
            "ts": time.time(),
            "data": data,
        }


def _t212_invalidate_cache(*endpoints):
    for ep in endpoints:
        t212_cache.pop(ep, None)


def t212_get(endpoint, params=None, use_cache=True, retries=2):
    with t212_lock:
        if use_cache:
            cached = _t212_get_cache(endpoint)
            if cached is not None:
                return cached

        for attempt in range(retries + 1):
            try:
                _t212_wait_for_rate_limit(endpoint)

                r = t212_session.get(
                    f"{T212_BASE}{endpoint}",
                    headers=t212_headers(),
                    params=params,
                    timeout=10,
                )
                t212_last_call[endpoint] = time.time()

                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                    wait_s = safe_float(retry_after, 6.0)
                    if wait_s <= 0:
                        wait_s = 6.0

                    add_log(f"T212 GET {endpoint}: 429 Too Many Requests, astept {wait_s:.1f}s", "warn")

                    if attempt < retries:
                        time.sleep(wait_s)
                        continue

                    return None

                r.raise_for_status()
                data = r.json()
                _t212_set_cache(endpoint, data)
                return data

            except Exception as e:
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue

                add_log(f"T212 GET {endpoint}: {e}", "err")
                return None

    return None


def t212_post(endpoint, body, retries=1):
    with t212_lock:
        for attempt in range(retries + 1):
            try:
                _t212_wait_for_rate_limit(endpoint)

                r = t212_session.post(
                    f"{T212_BASE}{endpoint}",
                    headers=t212_headers(),
                    json=body,
                    timeout=10,
                )
                t212_last_call[endpoint] = time.time()

                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                    wait_s = safe_float(retry_after, 6.0)
                    if wait_s <= 0:
                        wait_s = 6.0

                    add_log(f"T212 POST {endpoint}: 429 Too Many Requests, astept {wait_s:.1f}s", "warn")

                    if attempt < retries:
                        time.sleep(wait_s)
                        continue

                    return None

                r.raise_for_status()

                _t212_invalidate_cache(
                    "/equity/account/summary",
                    "/equity/portfolio",
                    "/equity/orders",
                )

                if r.content:
                    try:
                        return r.json()
                    except Exception:
                        return {"ok": True}

                return {"ok": True}

            except Exception as e:
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue

                add_log(f"T212 POST {endpoint}: {e}", "err")
                return None

    return None


def t212_delete(endpoint, retries=1):
    with t212_lock:
        for attempt in range(retries + 1):
            try:
                _t212_wait_for_rate_limit(endpoint)

                r = t212_session.delete(
                    f"{T212_BASE}{endpoint}",
                    headers=t212_headers(),
                    timeout=10,
                )
                t212_last_call[endpoint] = time.time()

                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                    wait_s = safe_float(retry_after, 6.0)
                    if wait_s <= 0:
                        wait_s = 6.0

                    add_log(f"T212 DELETE {endpoint}: 429 Too Many Requests, astept {wait_s:.1f}s", "warn")

                    if attempt < retries:
                        time.sleep(wait_s)
                        continue

                    return False

                r.raise_for_status()

                _t212_invalidate_cache(
                    "/equity/account/summary",
                    "/equity/portfolio",
                    "/equity/orders",
                )

                return True

            except Exception as e:
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue

                add_log(f"T212 DELETE {endpoint}: {e}", "err")
                return False

    return False


def get_account(force=False):
    return t212_get("/equity/account/summary", use_cache=not force)


def get_portfolio(force=False):
    return t212_get("/equity/portfolio", use_cache=not force)


def get_open_orders(force=False):
    data = t212_get("/equity/orders", use_cache=not force)
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────────────────────
# Alpaca Market Data
# ──────────────────────────────────────────────────────────────────────────────
def alpaca_headers():
    return {
        "APCA-API-KEY-ID": ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
    }


def get_price(symbol):
    try:
        r = alpaca_session.get(
            f"{ALPACA_DATA}/v2/stocks/{symbol}/quotes/latest",
            headers=alpaca_headers(),
            params={"feed": "iex"},
            timeout=8,
        )
        r.raise_for_status()

        data = r.json()
        quote = data.get("quote")
        if not isinstance(quote, dict):
            add_log(f"Price {symbol}: quote lipsa sau invalid", "warn")
            return None, None, None

        ask = safe_float(quote.get("ap"), 0.0)
        bid = safe_float(quote.get("bp"), 0.0)

        if ask > 0 and bid > 0:
            return (ask + bid) / 2.0, bid, ask
        if ask > 0:
            return ask, bid if bid > 0 else ask, ask
        if bid > 0:
            return bid, bid, ask if ask > 0 else bid

        add_log(f"Price {symbol}: bid/ask invalide", "warn")
        return None, None, None

    except Exception as e:
        add_log(f"Price {symbol}: {e}", "warn")
        return None, None, None


def get_bars(symbol, timeframe="1Hour", limit=80):
    try:
        r = alpaca_session.get(
            f"{ALPACA_DATA}/v2/stocks/{symbol}/bars",
            headers=alpaca_headers(),
            params={
                "timeframe": timeframe,
                "limit": limit,
                "feed": "iex",
                "adjustment": "raw",
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        raw_bars = data.get("bars")
        if not isinstance(raw_bars, list):
            add_log(f"Bars {symbol}: raspuns invalid de la Alpaca", "warn")
            return []

        cleaned = []
        for b in raw_bars:
            if not isinstance(b, dict):
                continue

            cleaned.append(
                {
                    "o": safe_float(b.get("o")),
                    "h": safe_float(b.get("h")),
                    "l": safe_float(b.get("l")),
                    "c": safe_float(b.get("c")),
                    "v": safe_int(b.get("v"), 0),
                    "t": b.get("t"),
                }
            )

        if not cleaned:
            add_log(f"Bars {symbol}: fara date pe {timeframe}", "warn")

        return cleaned

    except Exception as e:
        add_log(f"Bars {symbol}: {e}", "warn")
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Market Hours
# ──────────────────────────────────────────────────────────────────────────────
def get_market_status():
    try:
        r = alpaca_session.get(
            ALPACA_CLOCK,
            headers=alpaca_headers(),
            timeout=5,
        )
        r.raise_for_status()
        d = r.json()
        is_open = bool(d.get("is_open", False))
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
# ICT Strategy
# ──────────────────────────────────────────────────────────────────────────────
def calc_ema(closes, n):
    if not isinstance(closes, list) or len(closes) < n:
        return None

    k = 2 / (n + 1)
    e = closes[0]
    for c in closes[1:]:
        e = c * k + e * (1 - k)
    return e


def calc_atr(bars, n=14):
    if not isinstance(bars, list) or len(bars) < n + 1:
        return None

    trs = []
    for i in range(1, len(bars)):
        tr = max(
            bars[i]["h"] - bars[i]["l"],
            abs(bars[i]["h"] - bars[i - 1]["c"]),
            abs(bars[i]["l"] - bars[i - 1]["c"]),
        )
        trs.append(tr)

    return sum(trs[-n:]) / n if len(trs) >= n else None


def detect_regime(bars):
    period = 14
    mult = 1.5

    if not isinstance(bars, list) or len(bars) < period * 2 + 1:
        return "unknown"

    atr_now = calc_atr(bars[-(period + 1):], period)
    atr_avg = calc_atr(bars[-(period * 2 + 1):-period], period)

    if not atr_now or not atr_avg or atr_avg == 0:
        return "unknown"

    return "trending" if atr_now > atr_avg * mult else "ranging"


def detect_htf_bias(bars_d):
    if not isinstance(bars_d, list) or len(bars_d) < 50:
        return None

    closes = [b["c"] for b in bars_d]
    ema = calc_ema(closes[-50:], 50)
    if ema is None:
        return None

    return "BULLISH" if closes[-1] > ema else "BEARISH"


def detect_fvg(bars):
    if not isinstance(bars, list) or len(bars) < 3:
        return None

    for i in range(len(bars) - 1, max(1, len(bars) - 20), -1):
        if i < 2:
            continue

        c1, c3 = bars[i - 2], bars[i]

        if c1["h"] < c3["l"]:
            return {"type": "BULLISH", "mid": (c1["h"] + c3["l"]) / 2.0}

        if c1["l"] > c3["h"]:
            return {"type": "BEARISH", "mid": (c1["l"] + c3["h"]) / 2.0}

        body = abs(c3["c"] - c3["o"])
        overlap = c1["h"] - c3["l"]
        if body > 0 and 0 < overlap < body * 0.4:
            return {
                "type": "BULLISH" if c3["c"] > c3["o"] else "BEARISH",
                "mid": (c1["h"] + c3["l"]) / 2.0,
            }

    return None


def detect_sweep(bars):
    if not isinstance(bars, list) or len(bars) < 12:
        return None

    for i in range(len(bars) - 1, max(10, len(bars) - 9), -1):
        recent = bars[max(0, i - 10):i]
        last = bars[i]
        if not recent:
            continue

        sh = max(b["h"] for b in recent)
        sl = min(b["l"] for b in recent)

        if last["l"] < sl and last["c"] > sl:
            return "BULLISH_SWEEP"
        if last["h"] > sh and last["c"] < sh:
            return "BEARISH_SWEEP"

    return None


def detect_ema_cross(bars):
    if not isinstance(bars, list) or len(bars) < 15:
        return None

    closes = [b["c"] for b in bars]

    efn = calc_ema(closes[-5:], 5)
    esn = calc_ema(closes[-13:], 13)
    efp = calc_ema(closes[-6:-1], 5)
    esp = calc_ema(closes[-14:-1], 13)

    if None in (efn, esn, efp, esp):
        return None

    if efp <= esp and efn > esn:
        return "BULLISH_CROSS"
    if efp >= esp and efn < esn:
        return "BEARISH_CROSS"

    return None


def detect_momentum(bars, n=2):
    if not isinstance(bars, list) or len(bars) < n:
        return None

    last_n = bars[-n:]
    if all(b["c"] > b["o"] for b in last_n):
        return "BULLISH_MOM"
    if all(b["c"] < b["o"] for b in last_n):
        return "BEARISH_MOM"

    return None


def detect_rsi(bars, period=14):
    if not isinstance(bars, list) or len(bars) < period + 2:
        return None

    closes = [b["c"] for b in bars[-(period + 2):]]
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]

    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period

    if al == 0:
        return None

    rsi = 100 - 100 / (1 + ag / al)

    if rsi < 30:
        return "BULLISH_OVERSOLD"
    if rsi > 70:
        return "BEARISH_OVERBOUGHT"

    return None


def ict_scan(symbol):
    bars_1h = get_bars(symbol, "1Hour", 80)
    bars_1d = get_bars(symbol, "1Day", 60)

    if not isinstance(bars_1h, list) or not isinstance(bars_1d, list):
        add_log(f"Scan {symbol}: bars invalide", "warn")
        return None

    if len(bars_1h) == 0 or len(bars_1d) == 0:
        add_log(f"Scan {symbol}: fara suficiente date", "warn")
        return None

    bias = detect_htf_bias(bars_1d)
    regime = detect_regime(bars_1h)
    state["regime"] = regime

    if not bias:
        return None

    if regime in ("trending", "unknown"):
        fvg = detect_fvg(bars_1h)
        sw = detect_sweep(bars_1h)
        ema = detect_ema_cross(bars_1h)
        mom = detect_momentum(bars_1h)

        if bias == "BULLISH":
            if fvg and fvg["type"] == "BULLISH":
                return ("LONG", f"FVG {fvg['mid']:.2f}", regime)
            if sw == "BULLISH_SWEEP":
                return ("LONG", "Liq.Sweep", regime)
            if ema == "BULLISH_CROSS":
                return ("LONG", "EMA Cross", regime)
            if mom == "BULLISH_MOM":
                return ("LONG", "Momentum", regime)

        if bias == "BEARISH":
            if fvg and fvg["type"] == "BEARISH":
                return ("SHORT", f"FVG {fvg['mid']:.2f}", regime)
            if sw == "BEARISH_SWEEP":
                return ("SHORT", "Liq.Sweep", regime)
            if ema == "BEARISH_CROSS":
                return ("SHORT", "EMA Cross", regime)
            if mom == "BEARISH_MOM":
                return ("SHORT", "Momentum", regime)

    elif regime == "ranging":
        rsi = detect_rsi(bars_1h)
        if rsi == "BULLISH_OVERSOLD" and bias == "BULLISH":
            return ("LONG", "RSI<30", regime)
        if rsi == "BEARISH_OVERBOUGHT" and bias == "BEARISH":
            return ("SHORT", "RSI>70", regime)

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Execution
# ──────────────────────────────────────────────────────────────────────────────
def build_t212_ticker(symbol):
    return f"{symbol}_US_EQ"


def open_trade(symbol, direction, reason):
    mid, bid, ask = get_price(symbol)
    if not mid:
        add_log(f"Nu am pret pentru {symbol}", "err")
        return

    price = ask if direction == "LONG" else bid
    if not price or price <= 0:
        add_log(f"Pret invalid pentru {symbol}", "err")
        return

    balance = state["balance"]
    risk_usd = balance * (settings["risk_pct"] / 100.0)
    sl_pct = settings["sl_pct"] / 100.0
    tp_pct = sl_pct * settings["rr_ratio"]

    sl = price * (1 - sl_pct) if direction == "LONG" else price * (1 + sl_pct)
    tp = price * (1 + tp_pct) if direction == "LONG" else price * (1 - tp_pct)

    sl_dist = abs(price - sl)
    if sl_dist <= 0:
        add_log(f"SL invalid pentru {symbol}", "err")
        return

    shares = risk_usd / sl_dist
    shares = round(shares, 2)

    if shares <= 0:
        add_log(f"Size invalid pentru {symbol}: {shares}", "err")
        return

    max_notional = balance * 0.4
    notional = shares * price
    if notional > max_notional:
        shares = round(max_notional / price, 2)

    if shares <= 0:
        add_log(f"Size recalculat invalid pentru {symbol}: {shares}", "err")
        return

    qty = shares if direction == "LONG" else -shares
    ticker = build_t212_ticker(symbol)

    result = t212_post(
        "/equity/orders/market",
        {
            "ticker": ticker,
            "quantity": qty,
        },
    )

    if not result or "id" not in result:
        add_log(f"Ordin respins {symbol}: {result}", "err")
        return

    pos = {
        "id": str(result["id"]),
        "symbol": symbol,
        "ticker": ticker,
        "direction": direction,
        "entry": round(price, 4),
        "mark_price": round(price, 4),
        "sl": round(sl, 4),
        "tp": round(tp, 4),
        "shares": shares,
        "pnl_live": 0.0,
        "status": "open",
        "open_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "reason": reason,
        "regime": state.get("regime", "unknown"),
    }

    state["positions"].append(pos)
    add_log(
        f"{direction} {symbol} @ ${price:.2f} | SL:${sl:.2f} TP:${tp:.2f} | {shares} shares | {reason}",
        "ok",
    )


def close_trade(pos, reason):
    mid, bid, ask = get_price(pos["symbol"])
    exit_price = mid or pos.get("mark_price") or pos["entry"]

    qty = -pos["shares"] if pos["direction"] == "LONG" else pos["shares"]
    result = t212_post(
        "/equity/orders/market",
        {
            "ticker": pos["ticker"],
            "quantity": qty,
        },
    )

    if not result or "id" not in result:
        add_log(f"Eroare inchidere {pos['symbol']}: {result}", "err")
        return

    pnl = (
        (exit_price - pos["entry"]) * pos["shares"]
        if pos["direction"] == "LONG"
        else (pos["entry"] - exit_price) * pos["shares"]
    )

    pos["status"] = "closed"
    pos["close_time"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    pos["mark_price"] = round(exit_price, 4)
    pos["pnl_live"] = round(pnl, 2)

    state["pnl"] += pnl

    if pnl > 0:
        state["wins"] += 1
    else:
        state["losses"] += 1
        state["daily_dd"] += abs(pnl) / max(state["balance"], 1) * 100.0

    sl_dist = abs(pos["entry"] - pos["sl"])
    rr_value = abs((exit_price - pos["entry"]) / sl_dist) if sl_dist > 0 else 0
    rr = f"1:{rr_value:.1f}" if sl_dist > 0 else "—"

    state["history"].append(
        {
            "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "symbol": pos["symbol"],
            "dir": pos["direction"],
            "entry": pos["entry"],
            "exit": round(exit_price, 4),
            "shares": pos["shares"],
            "pnl": round(pnl, 2),
            "rr": rr,
            "reason": reason,
        }
    )

    add_log(
        f"{pos['symbol']} {reason} | ${pnl:+.2f} | {rr}",
        "ok" if pnl > 0 else "err",
    )

    if state["daily_dd"] >= settings["dd_limit"]:
        add_log(f"Daily DD {state['daily_dd']:.2f}% atins. Bot oprit.", "err")
        state["running"] = False

    clean_closed_positions()


def sync_positions():
    portfolio = get_portfolio()
    if not portfolio:
        return

    portfolio_map = {}

    if isinstance(portfolio, list):
        for p in portfolio:
            if isinstance(p, dict):
                portfolio_map[p.get("ticker", "")] = p
    elif isinstance(portfolio, dict):
        for p in portfolio.get("items", []):
            if isinstance(p, dict):
                portfolio_map[p.get("ticker", "")] = p

    for pos in state["positions"]:
        if pos.get("status") != "open":
            continue

        live = portfolio_map.get(pos["ticker"])
        if live:
            current_price = safe_float(live.get("currentPrice"), pos["entry"])
            ppl = safe_float(live.get("ppl"), 0.0)

            pos["mark_price"] = current_price
            pos["pnl_live"] = ppl

            hit_sl = (
                pos["direction"] == "LONG" and current_price <= pos["sl"]
            ) or (
                pos["direction"] == "SHORT" and current_price >= pos["sl"]
            )

            hit_tp = (
                pos["direction"] == "LONG" and current_price >= pos["tp"]
            ) or (
                pos["direction"] == "SHORT" and current_price <= pos["tp"]
            )

            if hit_tp:
                add_log(f"TP atins {pos['symbol']} @ ${current_price:.2f}", "warn")
                close_trade(pos, "TP hit")
            elif hit_sl:
                add_log(f"SL atins {pos['symbol']} @ ${current_price:.2f}", "warn")
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
    bal = safe_float(cash.get("availableToTrade"), 0.0)

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

    preferred_only = bool(settings.get("only_preferred_24_5", ONLY_PREFERRED_24_5))
    settings["symbols"] = filter_tradeable_symbols(settings["symbols"], preferred_only)
    state["symbol_mode"] = "preferred_24_5" if preferred_only else "allowed"

    add_log(
        f"Bot Stocks T212 pornit — mod simboluri: {'preferred 24/5' if preferred_only else 'allowed'}",
        "ok",
    )

    if not refresh_balance(force=True):
        add_log("Nu pot obtine balanta T212 — verifica API keys.", "err")
        state["running"] = False
        return

    add_log(f"Balanta T212: ${state['balance']:,.2f}", "ok")
    add_log(f"Simboluri active: {', '.join(settings['symbols'])}", "info")

    last_balance_refresh = 0.0

    while state["running"]:
        try:
            state["scan_count"] += 1
            state["last_scan"] = datetime.utcnow().strftime("%H:%M:%S")

            sync_positions()

            now = time.time()
            if now - last_balance_refresh >= 15:
                refresh_balance(force=False)
                last_balance_refresh = now

            is_open = get_market_status()

            add_log(
                f"Scan #{state['scan_count']} | Piata: {'DESCHISA' if is_open else 'INCHISA'} | {state['market'].upper()}"
            )

            if not is_open:
                add_log("Piata inchisa — astept NYSE open.", "warn")
            else:
                open_count = len([p for p in state["positions"] if p.get("status") == "open"])

                if open_count >= settings["max_positions"]:
                    add_log(f"Max {settings['max_positions']} pozitii active. Astept exit.", "warn")
                else:
                    for symbol in settings["symbols"]:
                        if not state["running"]:
                            break

                        if any(
                            p.get("status") == "open" and p.get("symbol") == symbol
                            for p in state["positions"]
                        ):
                            continue

                        add_log(f"Scanez {symbol}...", "info")

                        try:
                            sig = ict_scan(symbol)
                        except Exception as e:
                            add_log(f"Scan {symbol}: {e}", "err")
                            continue

                        if sig:
                            direction, reason, regime = sig
                            add_log(f"{symbol}: {direction} — {reason} [{regime}]", "warn")
                            open_trade(symbol, direction, reason)

                            open_count = len([p for p in state["positions"] if p.get("status") == "open"])
                            if open_count >= settings["max_positions"]:
                                break

                        time.sleep(1.5)

        except Exception as e:
            add_log(f"Eroare in bot_loop: {e}", "err")

        interval = safe_int(settings.get("scan_interval", 300), 300)
        if interval < 5:
            interval = 5

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
    total = state["wins"] + state["losses"]
    open_pos = [p for p in state["positions"] if p.get("status") == "open"]
    live_pnl = sum(p.get("pnl_live", 0) for p in open_pos)

    return jsonify(
        {
            "running": state["running"],
            "demo": T212_DEMO,
            "balance": round(state["balance"], 2),
            "pnl": round(state["pnl"], 2),
            "live_pnl": round(live_pnl, 2),
            "pnl_pct": round(state["pnl"] / max(start_balance, 1) * 100, 2),
            "daily_dd": round(state["daily_dd"], 2),
            "wins": state["wins"],
            "losses": state["losses"],
            "win_rate": round(state["wins"] / total * 100, 1) if total > 0 else 0,
            "active_positions": len(open_pos),
            "scan_count": state["scan_count"],
            "last_scan": state["last_scan"],
            "market": state["market"],
            "regime": state["regime"],
            "symbol_mode": state["symbol_mode"],
            "preferred_24_5_symbols": sorted(PREFERRED_24_5_SYMBOLS),
            "allowed_symbols": sorted(ALLOWED_SYMBOLS),
            "settings": settings,
        }
    )


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

    state["running"] = True
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

    preferred_only = settings.get("only_preferred_24_5", ONLY_PREFERRED_24_5)
    if "only_preferred_24_5" in data:
        preferred_only = bool(data.get("only_preferred_24_5"))
        settings["only_preferred_24_5"] = preferred_only
        state["symbol_mode"] = "preferred_24_5" if preferred_only else "allowed"

    if "symbols" in data:
        settings["symbols"] = normalize_symbols(data["symbols"], preferred_only)
        add_log(f"Simboluri active: {', '.join(settings['symbols'])}", "info")

    if "risk_pct" in data:
        settings["risk_pct"] = max(0.1, safe_float(data["risk_pct"], settings["risk_pct"]))

    if "dd_limit" in data:
        settings["dd_limit"] = max(0.5, safe_float(data["dd_limit"], settings["dd_limit"]))

    if "sl_pct" in data:
        settings["sl_pct"] = max(0.1, safe_float(data["sl_pct"], settings["sl_pct"]))

    if "rr_ratio" in data:
        settings["rr_ratio"] = max(0.5, safe_float(data["rr_ratio"], settings["rr_ratio"]))

    if "max_positions" in data:
        settings["max_positions"] = max(1, safe_int(data["max_positions"], settings["max_positions"]))

    if "scan_interval" in data:
        settings["scan_interval"] = max(5, safe_int(data["scan_interval"], settings["scan_interval"]))

    settings["symbols"] = filter_tradeable_symbols(settings["symbols"], preferred_only)

    add_log(
        f"Setari actualizate. Mod simboluri: {'preferred 24/5' if preferred_only else 'allowed'}",
        "info",
    )

    return jsonify({"ok": True, "settings": settings})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
