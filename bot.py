from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os
from datetime import datetime, time
import pytz
import time as pytime

app = Flask(__name__)

api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://api.alpaca.markets"
)

DEFAULT_NOTIONAL = 7000
EXTENDED_LIMIT_OFFSET = 0.03   # 3%

last_signal = {}

@app.route("/", methods=["GET"])
def home():
    return "ALIVE", 200

def is_regular_hours():
    eastern = pytz.timezone("US/Eastern")
    now = datetime.now(eastern).time()
    return time(9, 30) <= now <= time(16, 0)

def get_position(symbol):
    try:
        pos = api.get_position(symbol)
        return float(pos.qty)
    except:
        return 0

def get_quote(symbol):
    try:
        q = api.get_latest_quote(symbol)
        return float(q.ap), float(q.bp)
    except:
        return 0, 0

def calc_qty(notional, price):
    if price <= 0: return 0
    return int(notional / price)

def sell_qty(symbol, qty):
    if qty <= 0: return
    try:
        api.submit_order(symbol=symbol, qty=qty, side="sell", type="market", time_in_force="day", reduce_only=True)
        print(f"SELL {qty} {symbol}", flush=True)
    except Exception as e:
        print("SELL ERROR:", str(e), flush=True)

def close_position(symbol):
    try:
        api.close_position(symbol)
        print(f"FULL CLOSE executed for {symbol}", flush=True)
    except Exception as e:
        print("CLOSE ERROR:", str(e), flush=True)

# =========================
# FIXED NORMALIZER - Order Matters!
# =========================
def normalize_signal(raw):
    if not raw: 
        return ""
    
    s = str(raw).upper().strip()
    s = s.replace(" ", "").replace("-", "").replace("_", "").replace("|", "").replace(".", "")
    
    print(f"NORMALIZED: '{raw}' → '{s}'", flush=True)

    # Check EXIT signals FIRST (most important fix)
    if any(x in s for x in ["EXITLONG", "CLOSELONG", "EXIT", "CLOSE", "SL", "BE"]):
        return "EXIT_LONG"
    
    # Then OPEN signals
    if any(x in s for x in ["LONG", "ENTRY", "OPENLONG"]):
        return "OPEN_LONG"
    
    if "TP1" in s: return "TP1"
    if "TP2" in s: return "TP2"
    if "TP3" in s: return "TP3"
    if "TP4" in s: return "TP4"
    
    return ""

def already_fired(symbol, signal):
    key = f"{symbol}:{signal}"
    now = pytime.time()
    if key in last_signal and now - last_signal[key] < 1.5:
        return True
    last_signal[key] = now
    return False

# =========================
# WEBHOOK
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        raw = request.get_data(as_text=False)
        print("=== RAW WEBHOOK RECEIVED ===", flush=True)
        print(raw, flush=True)

        data = None
        try:
            data = request.get_json(force=True, silent=True)
        except:
            pass
        if not data and raw:
            try:
                import json
                data = json.loads(raw.decode('utf-8'))
            except:
                pass

        print("PARSED DATA:", data, flush=True)

        if not data:
            return jsonify({"status": "no_data"}), 200

        symbol = data.get("ticker") or data.get("symbol") or data.get("SYMBOL") or data.get("TICKER")
        raw_signal = data.get("signal")
        notional = float(data.get("notional") or DEFAULT_NOTIONAL)

        signal = normalize_signal(raw_signal)
        print(f"FINAL PARSED → {symbol} | Raw: {raw_signal} → {signal} | Notional: ${notional}", flush=True)

        if not symbol or not signal:
            return jsonify({"status": "bad_payload"}), 200

        if already_fired(symbol, signal):
            return jsonify({"status": "duplicate"}), 200

        qty_pos = get_position(symbol)
        regular = is_regular_hours()

        if signal == "OPEN_LONG":
            if qty_pos > 0:
                return jsonify({"status": "already_in_position"}), 200

            ask, _ = get_quote(symbol)
            qty = calc_qty(notional, ask)
            if qty <= 0:
                return jsonify({"status": "qty_fail"}), 200

            if regular:
                api.submit_order(symbol=symbol, qty=qty, side="buy", type="market", time_in_force="day")
                print(f"MARKET BUY {qty} {symbol} (Regular Hours)", flush=True)
            else:
                limit_price = round(ask * (1 + EXTENDED_LIMIT_OFFSET), 2)
                try:
                    api.submit_order(
                        symbol=symbol, qty=qty, side="buy", type="limit",
                        time_in_force="day", limit_price=limit_price, extended_hours=True
                    )
                    print(f"LIMIT BUY {qty} {symbol} @ {limit_price} (Extended - 3%)", flush=True)
                except Exception as e:
                    print(f"Extended order REJECTED: {e}", flush=True)

            return jsonify({"status": "entry_sent"}), 200

        if signal == "EXIT_LONG":
            if qty_pos > 0:
                close_position(symbol)
            else:
                print(f"EXIT signal - No position in {symbol}", flush=True)
            return jsonify({"status": "exit_sent"}), 200

        if qty_pos <= 0:
            return jsonify({"status": "no_position"}), 200

        qty = float(qty_pos)
        if signal == "TP1": sell_qty(symbol, int(qty * 0.25))
        elif signal == "TP2": sell_qty(symbol, int(qty * 0.20))
        elif signal == "TP3": sell_qty(symbol, int(qty * 0.10))
        elif signal == "TP4": sell_qty(symbol, int(qty * 0.10))

        return jsonify({"status": "processed"}), 200

    except Exception as e:
        print("WEBHOOK ERROR:", str(e), flush=True)
        return jsonify({"status": "error"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
