from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os
from datetime import datetime, time
import pytz
import time as pytime

app = Flask(__name__)

# ==================== PAPER TRADING ====================
api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://paper-api.alpaca.markets"   # ← PAPER ACCOUNT
)

DEFAULT_NOTIONAL = 7000
EXTENDED_LIMIT_OFFSET = 0.02
TRAILING_STOP_PERCENT = 0.5

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

def place_trailing_stop(symbol):
    qty = get_position(symbol)
    if qty <= 0:
        return
    try:
        api.submit_order(
            symbol=symbol,
            qty=qty,
            side="sell",
            type="trailing_stop",
            time_in_force="day",
            trail_percent=TRAILING_STOP_PERCENT
        )
        print(f"✅ PAPER TRAILING STOP {TRAILING_STOP_PERCENT}% placed for {symbol}", flush=True)
    except Exception as e:
        print(f"Trailing stop failed: {e}", flush=True)

def sell_qty(symbol, qty, is_extended=False):
    if qty <= 0: return
    try:
        if is_extended:
            _, bid = get_quote(symbol)
            limit_price = round(bid * (1 - 0.008), 2) if bid > 0 else None
            if limit_price:
                api.submit_order(symbol=symbol, qty=qty, side="sell", type="limit",
                               time_in_force="day", limit_price=limit_price, extended_hours=True)
                print(f"LIMIT SELL {qty} {symbol} @ {limit_price} (Extended)", flush=True)
            else:
                api.submit_order(symbol=symbol, qty=qty, side="sell", type="market", time_in_force="day")
                print(f"MARKET SELL {qty} {symbol} (Ext fallback)", flush=True)
        else:
            api.submit_order(symbol=symbol, qty=qty, side="sell", type="market", time_in_force="day")
            print(f"MARKET SELL {qty} {symbol}", flush=True)
    except Exception as e:
        print(f"SELL ERROR: {e}", flush=True)

def close_position(symbol, is_extended=False):
    qty = get_position(symbol)
    if qty > 0:
        sell_qty(symbol, qty, is_extended)

def normalize_signal(raw):
    if not raw: return ""
    s = str(raw).upper().strip().replace(" ", "").replace("-", "").replace("_", "").replace(".", "")
    print(f"NORMALIZED: '{raw}' → '{s}'", flush=True)

    if any(x in s for x in ["EXITLONG", "CLOSELONG", "EXIT", "CLOSE", "SL", "BE"]):
        return "EXIT_LONG"
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

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        raw_bytes = request.get_data(as_text=False)
        print("=== RAW WEBHOOK RECEIVED ===", flush=True)
        print(raw_bytes, flush=True)

        data = None
        try:
            data = request.get_json(force=True, silent=True)
        except:
            pass
        if not data and raw_bytes:
            try:
                import json
                data = json.loads(raw_bytes.decode('utf-8', errors='ignore'))
            except:
                pass

        print("PARSED DATA:", data, flush=True)

        if not data:
            raw_text = raw_bytes.decode('utf-8', errors='ignore').strip()
            print(f"RAW TEXT: {raw_text}", flush=True)
            if "{{strategy.order.alert_message}}" in raw_text:
                print("🚨 TEMPLATE RECEIVED", flush=True)
            return jsonify({"status": "no_data"}), 200

        symbol = data.get("ticker") or data.get("symbol")
        raw_signal = data.get("signal")
        signal = normalize_signal(raw_signal)

        print(f"FINAL PARSED → {symbol} | {raw_signal} → {signal}", flush=True)

        if not symbol or not signal:
            return jsonify({"status": "bad_payload"}), 200

        if already_fired(symbol, signal):
            return jsonify({"status": "duplicate"}), 200

        qty_pos = get_position(symbol)
        extended = not is_regular_hours()

        if signal == "OPEN_LONG":
            if qty_pos > 0:
                return jsonify({"status": "already_in_position"}), 200

            ask, _ = get_quote(symbol)
            qty = calc_qty(DEFAULT_NOTIONAL, ask)
            if qty <= 0:
                return jsonify({"status": "qty_fail"}), 200

            if not extended:
                api.submit_order(symbol=symbol, qty=qty, side="buy", type="market", time_in_force="day")
                print(f"MARKET BUY {qty} {symbol}", flush=True)
            else:
                limit_price = round(ask * (1 + EXTENDED_LIMIT_OFFSET), 2)
                api.submit_order(symbol=symbol, qty=qty, side="buy", type="limit",
                               time_in_force="day", limit_price=limit_price, extended_hours=True)
                print(f"LIMIT BUY {qty} {symbol} @ {limit_price}", flush=True)

            pytime.sleep(4)
            place_trailing_stop(symbol)
            return jsonify({"status": "entry_sent"}), 200

        if signal == "EXIT_LONG":
            close_position(symbol, extended)
            return jsonify({"status": "exit_sent"}), 200

        if qty_pos <= 0:
            print(f"TP/SL ignored - No position", flush=True)
            return jsonify({"status": "no_position"}), 200

        qty = float(qty_pos)
        sold = 0
        if signal == "TP1": sold = int(qty * 0.25)
        elif signal == "TP2": sold = int(qty * 0.20)
        elif signal == "TP3": sold = int(qty * 0.10)
        elif signal == "TP4": sold = int(qty * 0.10)

        if sold > 0:
            sell_qty(symbol, sold, extended)
            print(f"✅ TP{signal[-1]}: Sold {sold} of {int(qty)}", flush=True)

        return jsonify({"status": "processed"}), 200

    except Exception as e:
        print("WEBHOOK ERROR:", str(e), flush=True)
        return jsonify({"status": "error"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
