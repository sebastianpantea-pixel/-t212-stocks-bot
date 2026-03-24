"""
ICT Stocks Bot — Trading 212 Paper Trading
Date: Alpaca Market Data (gratuit)
Executie: Trading 212 API
"""

import os, time, threading, math, base64
from datetime import datetime, timezone
import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

# ─── Config ───────────────────────────────────────────────────────────────────
T212_KEY    = os.environ.get("T212_API_KEY", "")
T212_SECRET = os.environ.get("T212_API_SECRET", "")
T212_DEMO   = os.environ.get("T212_DEMO", "true").lower() == "true"
T212_BASE   = "https://demo.trading212.com/api/v0" if T212_DEMO else "https://live.trading212.com/api/v0"

# Alpaca pentru date de pret
ALPACA_KEY    = os.environ.get("ALPACA_KEY_ID", "")
ALPACA_SECRET = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_DATA   = "https://data.alpaca.markets"

# ─── State ────────────────────────────────────────────────────────────────────
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
    "symbols":       ["AAPL", "NVDA", "MSFT", "SPY", "QQQ", "TSLA", "AMZN", "META"],
    "risk_pct":      1.0,
    "dd_limit":      5.0,
    "sl_pct":        1.5,
    "rr_ratio":      3.0,
    "max_positions": 3,
    "scan_interval": 300,
}

bot_thread    = None
start_balance = 0.0

# ─── Logging ──────────────────────────────────────────────────────────────────
def add_log(msg, level="info"):
    entry = {"time": datetime.utcnow().strftime("%H:%M:%S"), "msg": msg, "level": level}
    state["log"].insert(0, entry)
    if len(state["log"]) > 200:
        state["log"] = state["log"][:200]
    print(f"[{entry['time']}] {msg}")

# ─── Trading 212 API ──────────────────────────────────────────────────────────
def t212_headers():
    creds = base64.b64encode(f"{T212_KEY}:{T212_SECRET}".encode()).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Content-Type":  "application/json"
    }

def t212_get(endpoint, params=None):
    try:
        r = requests.get(f"{T212_BASE}{endpoint}",
                         headers=t212_headers(), params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        add_log(f"T212 GET {endpoint}: {e}", "err")
        return None

def t212_post(endpoint, body):
    try:
        r = requests.post(f"{T212_BASE}{endpoint}",
                          headers=t212_headers(), json=body, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        add_log(f"T212 POST {endpoint}: {e}", "err")
        return None

def t212_delete(endpoint):
    try:
        r = requests.delete(f"{T212_BASE}{endpoint}",
                            headers=t212_headers(), timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        add_log(f"T212 DELETE {endpoint}: {e}", "err")
        return False

def get_account():
    return t212_get("/equity/account/summary")

def get_portfolio():
    return t212_get("/equity/portfolio")

def get_open_orders():
    data = t212_get("/equity/orders")
    return data if isinstance(data, list) else []

# ─── Alpaca Market Data ───────────────────────────────────────────────────────
def alpaca_headers():
    return {
        "APCA-API-KEY-ID":     ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
    }

def get_price(symbol):
    try:
        r = requests.get(f"{ALPACA_DATA}/v2/stocks/{symbol}/quotes/latest",
                         headers=alpaca_headers(), params={"feed": "iex"}, timeout=8)
        r.raise_for_status()
        q = r.json().get("quote", {})
        ask = float(q.get("ap", 0))
        bid = float(q.get("bp", 0))
        if ask > 0 and bid > 0:
            return (ask + bid) / 2, bid, ask
    except Exception as e:
        add_log(f"Price {symbol}: {e}", "warn")
    return None, None, None

def get_bars(symbol, timeframe="1Hour", limit=80):
    try:
        r = requests.get(f"{ALPACA_DATA}/v2/stocks/{symbol}/bars",
                         headers=alpaca_headers(),
                         params={"timeframe": timeframe, "limit": limit,
                                 "feed": "iex", "adjustment": "raw"}, timeout=10)
        r.raise_for_status()
        data = r.json()
        return [{"o": float(b["o"]), "h": float(b["h"]),
                 "l": float(b["l"]), "c": float(b["c"]),
                 "v": int(b.get("v", 0)), "t": b["t"]}
                for b in data.get("bars", [])]
    except Exception as e:
        add_log(f"Bars {symbol}: {e}", "warn")
        return []

# ─── Market Hours ─────────────────────────────────────────────────────────────
def get_market_status():
    try:
        r = requests.get("https://paper-api.alpaca.markets/v2/clock",
                         headers=alpaca_headers(), timeout=5)
        r.raise_for_status()
        d = r.json()
        is_open = d.get("is_open", False)
        state["market"] = "open" if is_open else "closed"
        return is_open
    except:
        pass
    # Fallback manual: NYSE 09:30-16:00 ET = 13:30-20:00 UTC
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        state["market"] = "weekend"
        return False
    h = now.hour + now.minute / 60
    is_open = 13.5 <= h < 20.0
    state["market"] = "open" if is_open else "closed"
    return is_open

# ─── ICT Strategy ─────────────────────────────────────────────────────────────
def calc_ema(closes, n):
    if len(closes) < n: return None
    k = 2 / (n + 1); e = closes[0]
    for c in closes[1:]: e = c * k + e * (1 - k)
    return e

def calc_atr(bars, n=14):
    if len(bars) < n + 1: return None
    trs = [max(bars[i]["h"] - bars[i]["l"],
               abs(bars[i]["h"] - bars[i-1]["c"]),
               abs(bars[i]["l"] - bars[i-1]["c"])) for i in range(1, len(bars))]
    return sum(trs[-n:]) / n

def detect_regime(bars):
    period = 14; mult = 1.5
    if len(bars) < period * 2 + 1: return "unknown"
    atr_now = calc_atr(bars[-(period+1):], period)
    atr_avg = calc_atr(bars[-(period*2+1):-period], period)
    if not atr_now or not atr_avg or atr_avg == 0: return "unknown"
    return "trending" if atr_now > atr_avg * mult else "ranging"

def detect_htf_bias(bars_d):
    if len(bars_d) < 50: return None
    closes = [b["c"] for b in bars_d]
    ema = calc_ema(closes[-50:], 50)
    return "BULLISH" if closes[-1] > ema else "BEARISH"

def detect_fvg(bars):
    for i in range(len(bars)-1, max(1, len(bars)-20), -1):
        if i < 2: continue
        c1, c3 = bars[i-2], bars[i]
        if c1["h"] < c3["l"]:
            return {"type": "BULLISH", "mid": (c1["h"] + c3["l"]) / 2}
        if c1["l"] > c3["h"]:
            return {"type": "BEARISH", "mid": (c1["l"] + c3["h"]) / 2}
        body = abs(c3["c"] - c3["o"])
        overlap = c1["h"] - c3["l"]
        if body > 0 and 0 < overlap < body * 0.4:
            return {"type": "BULLISH" if c3["c"] > c3["o"] else "BEARISH",
                    "mid": (c1["h"] + c3["l"]) / 2}
    return None

def detect_sweep(bars):
    for i in range(len(bars)-1, max(10, len(bars)-9), -1):
        recent = bars[max(0, i-10):i]
        last   = bars[i]
        if not recent: continue
        sh = max(b["h"] for b in recent)
        sl = min(b["l"] for b in recent)
        if last["l"] < sl and last["c"] > sl: return "BULLISH_SWEEP"
        if last["h"] > sh and last["c"] < sh: return "BEARISH_SWEEP"
    return None

def detect_ema_cross(bars):
    if len(bars) < 15: return None
    closes = [b["c"] for b in bars]
    efn = calc_ema(closes[-5:],    5)
    esn = calc_ema(closes[-13:],   13)
    efp = calc_ema(closes[-6:-1],  5)
    esp = calc_ema(closes[-14:-1], 13)
    if None in (efn, esn, efp, esp): return None
    if efp <= esp and efn > esn: return "BULLISH_CROSS"
    if efp >= esp and efn < esn: return "BEARISH_CROSS"
    return None

def detect_momentum(bars, n=2):
    if len(bars) < n: return None
    last_n = bars[-n:]
    if all(b["c"] > b["o"] for b in last_n): return "BULLISH_MOM"
    if all(b["c"] < b["o"] for b in last_n): return "BEARISH_MOM"
    return None

def detect_rsi(bars, period=14):
    if len(bars) < period + 2: return None
    closes = [b["c"] for b in bars[-(period+2):]]
    gains  = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0: return None
    rsi = 100 - 100 / (1 + ag / al)
    if rsi < 30: return "BULLISH_OVERSOLD"
    if rsi > 70: return "BEARISH_OVERBOUGHT"
    return None

def ict_scan(symbol):
    bars_1h = get_bars(symbol, "1Hour", 80)
    bars_1d = get_bars(symbol, "1Day",  60)
    if not bars_1h or not bars_1d:
        return None
    bias   = detect_htf_bias(bars_1d)
    regime = detect_regime(bars_1h)
    state["regime"] = regime
    if not bias: return None

    if regime in ("trending", "unknown"):
        fvg  = detect_fvg(bars_1h)
        sw   = detect_sweep(bars_1h)
        ema  = detect_ema_cross(bars_1h)
        mom  = detect_momentum(bars_1h)
        if bias == "BULLISH":
            if fvg and fvg["type"] == "BULLISH": return ("LONG",  f"FVG {fvg['mid']:.2f}", regime)
            if sw  == "BULLISH_SWEEP":           return ("LONG",  "Liq.Sweep",              regime)
            if ema == "BULLISH_CROSS":           return ("LONG",  "EMA Cross",              regime)
            if mom == "BULLISH_MOM":             return ("LONG",  "Momentum",               regime)
        if bias == "BEARISH":
            if fvg and fvg["type"] == "BEARISH": return ("SHORT", f"FVG {fvg['mid']:.2f}", regime)
            if sw  == "BEARISH_SWEEP":           return ("SHORT", "Liq.Sweep",              regime)
            if ema == "BEARISH_CROSS":           return ("SHORT", "EMA Cross",              regime)
            if mom == "BEARISH_MOM":             return ("SHORT", "Momentum",               regime)
    elif regime == "ranging":
        rsi = detect_rsi(bars_1h)
        if rsi == "BULLISH_OVERSOLD"   and bias == "BULLISH": return ("LONG",  "RSI<30", regime)
        if rsi == "BEARISH_OVERBOUGHT" and bias == "BEARISH": return ("SHORT", "RSI>70", regime)
    return None

# ─── Order Execution ──────────────────────────────────────────────────────────
def open_trade(symbol, direction, reason):
    mid, bid, ask = get_price(symbol)
    if not mid:
        add_log(f"Nu am pret pentru {symbol}", "err")
        return

    price    = ask if direction == "LONG" else bid
    balance  = state["balance"]
    risk_usd = balance * (settings["risk_pct"] / 100)
    sl_pct   = settings["sl_pct"] / 100
    tp_pct   = sl_pct * settings["rr_ratio"]

    sl = price * (1 - sl_pct) if direction == "LONG" else price * (1 + sl_pct)
    tp = price * (1 + tp_pct) if direction == "LONG" else price * (1 - tp_pct)

    sl_dist = abs(price - sl)
    shares  = risk_usd / sl_dist if sl_dist > 0 else 0
    # T212 suporta fractional — rotunjim la 2 zecimale
    shares  = round(shares, 2)
    if shares <= 0 or shares * price > balance * 0.4:
        add_log(f"Size invalid pentru {symbol}: {shares} shares @ ${price:.2f}", "err")
        return

    # T212: cantitate pozitiva = BUY, negativa = SELL (short)
    qty = shares if direction == "LONG" else -shares

    # T212 foloseste ticker format diferit (ex: AAPL_US_EQ)
    ticker = f"{symbol}_US_EQ"

    result = t212_post("/equity/orders/market", {
        "ticker":   ticker,
        "quantity": qty,
    })

    if not result or "id" not in result:
        add_log(f"Ordin respins {symbol}: {result}", "err")
        return

    pos = {
        "id":         str(result["id"]),
        "symbol":     symbol,
        "ticker":     ticker,
        "direction":  direction,
        "entry":      price,
        "mark_price": price,
        "sl":         sl,
        "tp":         tp,
        "shares":     shares,
        "pnl_live":   0.0,
        "status":     "open",
        "open_time":  datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "reason":     reason,
        "regime":     direction,
    }
    state["positions"].append(pos)
    add_log(f"✅ {direction} {symbol} @ ${price:.2f} | SL:${sl:.2f} TP:${tp:.2f} | {shares} shares | {reason}", "ok")

def close_trade(pos, reason):
    """Inchide pozitia cu market order invers"""
    mid, bid, ask = get_price(pos["symbol"])
    exit_price = mid or pos["mark_price"]

    qty = -pos["shares"] if pos["direction"] == "LONG" else pos["shares"]
    result = t212_post("/equity/orders/market", {
        "ticker":   pos["ticker"],
        "quantity": qty,
    })

    if result and "id" in result:
        pnl = (exit_price - pos["entry"]) * pos["shares"] if pos["direction"] == "LONG" \
              else (pos["entry"] - exit_price) * pos["shares"]
        pos["status"] = "closed"
        state["pnl"] += pnl
        if pnl > 0:
            state["wins"] += 1
        else:
            state["losses"] += 1
            state["daily_dd"] += abs(pnl) / max(state["balance"], 1) * 100

        sl_dist = abs(pos["entry"] - pos["sl"])
        rr = f"1:{abs((exit_price-pos['entry'])/sl_dist):.1f}" if sl_dist > 0 else "—"

        state["history"].append({
            "date":   datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "symbol": pos["symbol"], "dir": pos["direction"],
            "entry":  pos["entry"],  "exit": exit_price,
            "shares": pos["shares"], "pnl": round(pnl, 2),
            "rr":     rr,            "reason": reason,
        })
        add_log(f"{'✅' if pnl>0 else '❌'} {pos['symbol']} {reason} | ${pnl:+.2f} | {rr}", "ok" if pnl>0 else "err")

        if state["daily_dd"] >= settings["dd_limit"]:
            add_log(f"⛔ Daily DD {state['daily_dd']:.2f}% atins. Bot oprit!", "err")
            state["running"] = False
    else:
        add_log(f"Eroare inchidere {pos['symbol']}: {result}", "err")

def sync_positions():
    """Sync pozitii si verifica SL/TP intern"""
    portfolio = get_portfolio()
    if not portfolio: return

    # Pozitiile T212 indexate dupa ticker
    portfolio_map = {}
    if isinstance(portfolio, list):
        for p in portfolio:
            portfolio_map[p.get("ticker", "")] = p
    elif isinstance(portfolio, dict):
        for p in portfolio.get("items", []):
            portfolio_map[p.get("ticker", "")] = p

    for pos in state["positions"]:
        if pos["status"] != "open": continue
        live = portfolio_map.get(pos["ticker"])
        if live:
            pos["mark_price"] = float(live.get("currentPrice", pos["entry"]))
            pos["pnl_live"]   = float(live.get("ppl", 0))
            mark = pos["mark_price"]
            # Verifica SL/TP intern
            hit_sl = (pos["direction"] == "LONG"  and mark <= pos["sl"]) or \
                     (pos["direction"] == "SHORT" and mark >= pos["sl"])
            hit_tp = (pos["direction"] == "LONG"  and mark >= pos["tp"]) or \
                     (pos["direction"] == "SHORT" and mark <= pos["tp"])
            if hit_tp:
                add_log(f"🎯 TP atins {pos['symbol']} @ ${mark:.2f}", "warn")
                close_trade(pos, "TP hit ✓")
            elif hit_sl:
                add_log(f"🛑 SL atins {pos['symbol']} @ ${mark:.2f}", "warn")
                close_trade(pos, "SL hit")
        else:
            # Pozitia nu mai e in portfolio — inchisa extern
            if pos.get("pnl_live") is not None:
                pnl = pos.get("pnl_live", 0)
                pos["status"] = "closed"
                state["pnl"] += pnl
                if pnl > 0: state["wins"] += 1
                else: state["losses"] += 1
                state["history"].append({
                    "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                    "symbol": pos["symbol"], "dir": pos["direction"],
                    "entry": pos["entry"], "exit": pos["mark_price"],
                    "shares": pos["shares"], "pnl": round(pnl, 2),
                    "rr": "—", "reason": "Inchis extern"
                })
                add_log(f"{'✅' if pnl>0 else '❌'} {pos['symbol']} inchis extern | ${pnl:+.2f}", "ok" if pnl>0 else "err")

# ─── Bot Loop ─────────────────────────────────────────────────────────────────
def bot_loop():
    global start_balance
    add_log("🟢 Bot Stocks T212 pornit — Paper Trading", "ok")

    acc = get_account()
    if acc:
        bal = float(acc.get("cash", {}).get("availableToTrade", 0) or
                    acc.get("totalValue", 0))
        if bal > 0:
            state["balance"] = bal
            start_balance    = bal
            add_log(f"Balanta T212: ${bal:,.2f}", "ok")
        else:
            add_log(f"Balanta: {acc}", "warn")
    else:
        add_log("Nu pot obtine balanta T212 — verifica API keys.", "err")
        state["running"] = False
        return

    while state["running"]:
        try:
            state["scan_count"] += 1
            state["last_scan"]   = datetime.utcnow().strftime("%H:%M:%S")

            sync_positions()

            # Refresh balanta
            acc = get_account()
            if acc:
                bal = float(acc.get("cash", {}).get("availableToTrade", state["balance"]))
                if bal > 0: state["balance"] = bal

            is_open = get_market_status()
            add_log(f"Scan #{state['scan_count']} | Piata: {'DESCHISA' if is_open else 'INCHISA'} | {state['market'].upper()}")

            if not is_open:
                add_log("Piata inchisa — astept NYSE open (15:30 RO).", "warn")
            else:
                open_count = len([p for p in state["positions"] if p["status"] == "open"])
                if open_count >= settings["max_positions"]:
                    add_log(f"Max {settings['max_positions']} pozitii active. Astept exit.")
                else:
                    for symbol in settings["symbols"]:
                        if not state["running"]: break
                        # Skip daca avem deja pozitie pe symbol
                        if any(p["status"] == "open" and p["symbol"] == symbol
                               for p in state["positions"]):
                            continue
                        add_log(f"Scanez {symbol}...")
                        sig = ict_scan(symbol)
                        if sig:
                            direction, reason, regime = sig
                            add_log(f"📊 {symbol}: {direction} — {reason} [{regime}]", "warn")
                            open_trade(symbol, direction, reason)
                        time.sleep(2)

        except Exception as e:
            add_log(f"Eroare: {e}", "err")

        interval = settings.get("scan_interval", 300)
        for _ in range(interval):
            if not state["running"]: break
            time.sleep(1)

    add_log("⛔ Bot oprit.", "warn")

# ─── API ──────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/status")
def api_status():
    total    = state["wins"] + state["losses"]
    open_pos = [p for p in state["positions"] if p["status"] == "open"]
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
    data = request.get_json()
    for k in ["symbols", "risk_pct", "dd_limit", "sl_pct", "rr_ratio", "max_positions", "scan_interval"]:
        if k in data: settings[k] = data[k]
    add_log("Setari actualizate.", "info")
    return jsonify({"ok": True, "settings": settings})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
