from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os
from datetime import datetime, time
import pytz
import time as pytime
import json

app = Flask(__name__)

# =========================================================
# ALPACA CONFIG
# =========================================================

api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://api.alpaca.markets"
)

# =========================================================
# SETTINGS
# =========================================================

DEFAULT_NOTIONAL = 3500
last_signal = {}

# =========================================================
# BASIC HELPERS
# =========================================================

def is_regular_hours():
    eastern = pytz.timezone("US/Eastern")
    now = datetime.now(eastern).time()
    return time(9, 30) <= now <= time(16, 0)

def get_position(symbol):
    try:
        return float(api.get_position(symbol).qty)
    except:
        return 0

def get_trade_price(symbol):
    try:
        return float(api.get_latest_trade(symbol).price)
    except:
        return 0

def calc_qty(notional, price):
    if price <= 0:
        return 0
    return int(notional / price)

# =========================================================
# DUPLICATE FILTER
# =========================================================

def already_fired(symbol, signal):
    key = f"{symbol}:{signal}"
    now = pytime.time()

    if key in last_signal and now - last_signal[key] < 2:
        return True

    last_signal[key] = now
    return False

# =========================================================
# SIGNAL NORMALIZER (FIXED PRIORITY LOGIC)
# =========================================================

def normalize_signal(raw):

    if not raw:
        return ""

    s = str(raw).upper().strip()

    s_clean = (
        s.replace(" ", "")
         .replace("-", "")
         .replace("_", "")
         .replace(".", "")
    )

    # =========================
    # EXIT FIRST (highest priority)
    # =========================
    if any(x in s_clean for x in [
        "EXITLONG",
        "CLOSELONG",
        "EXIT",
        "CLOSE",
        "SL",
        "BE",
        "BREAKEVEN"
    ]):
        return "EXIT_LONG"

    # =========================
    # TAKE PROFITS
    # =========================
    if "TP1" in s_clean:
        return "TP1"
    if "TP2" in s_clean:
        return "TP2"
    if "TP3" in s_clean:
        return "TP3"
    if "TP4" in s_clean:
        return "TP4"

    # =========================
    # ENTRY (accept ALL variants)
    # =========================
    if "LONG" in s_clean:
        return "OPEN_LONG"

    return ""

# =========================================================
# SELL (UNCHANGED LOGIC)
# =========================================================

def sell_qty(symbol, qty, is_extended=False):

    if qty <= 0:
        return

    try:
        order = api.submit_order(
            symbol=symbol,
            qty=qty,
            side="sell",
            type="market",
            time_in_force="day"
        )

        print(f"SELL {qty} {symbol}", flush=True)
        print(f"ORDER ID: {order.id}", flush=True)

    except Exception as e:
        print(f"SELL ERROR: {e}", flush=True)

# =========================================================
# CLOSE POSITION
# =========================================================

def close_position(symbol, is_extended=False):

    qty = get_position(symbol)

    if qty > 0:
        sell_qty(symbol, qty, is_extended)
    else:
        print(f"NO POSITION {symbol}", flush=True)

# =========================================================
# WEBHOOK
# =========================================================

@app.route("/webhook", methods=["POST"])
def webhook():

    try:
        raw_bytes = request.get_data(as_text=False)

        data = None

        try:
            data = request.get_json(force=True, silent=True)
        except:
            pass

        if not data and raw_bytes:
            try:
                data = json.loads(raw_bytes.decode("utf-8", errors="ignore"))
            except:
                pass

        if not data:
            return jsonify({"status": "no_data"}), 200

        symbol = data.get("ticker") or data.get("symbol")
        raw_signal = data.get("signal")

        signal = normalize_signal(raw_signal)

        if not symbol or not signal:
            return jsonify({"status": "bad_payload"}), 200

        if already_fired(symbol, signal):
            return jsonify({"status": "duplicate"}), 200

        qty_pos = get_position(symbol)
        extended = not is_regular_hours()

        print(f"{symbol} | {raw_signal} → {signal}", flush=True)
        print(f"POSITION: {qty_pos}", flush=True)

        # =================================================
        # ENTRY
        # =================================================

        if signal == "OPEN_LONG":

            if qty_pos > 0:
                return jsonify({"status": "already_in_position"}), 200

            price = get_trade_price(symbol)

            if price <= 0:
                return jsonify({"status": "bad_price"}), 200

            notional = float(data.get("notional", DEFAULT_NOTIONAL))
            qty = calc_qty(notional, price)

            if qty <= 0:
                return jsonify({"status": "qty_fail"}), 200

            try:
                order = api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="buy",
                    type="market",
                    time_in_force="day"
                )

                print(f"BUY {qty} {symbol}", flush=True)
                print(f"ORDER ID: {order.id}", flush=True)

            except Exception as e:
                print(f"BUY ERROR: {e}", flush=True)

            return jsonify({"status": "entry_sent"}), 200

        # =================================================
        # EXIT
        # =================================================

        if signal == "EXIT_LONG":
            close_position(symbol, extended)
            return jsonify({"status": "exit_sent"}), 200

        # =================================================
        # TP HANDLING
        # =================================================

        if qty_pos <= 0:
            return jsonify({"status": "no_position"}), 200

        qty = float(qty_pos)

        if signal == "TP1":
            sell_qty(symbol, int(qty * 0.20), extended)

        elif signal == "TP2":
            sell_qty(symbol, int(qty * 0.10), extended)

        elif signal == "TP3":
            sell_qty(symbol, int(qty * 0.05), extended)

        elif signal == "TP4":
            sell_qty(symbol, int(qty * 0.05), extended)

        return jsonify({"status": "processed"}), 200

    except Exception as e:
        print(f"WEBHOOK ERROR: {e}", flush=True)
        return jsonify({"status": "error"}), 200


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)
