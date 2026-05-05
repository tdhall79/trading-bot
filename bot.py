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

# =========================
# CONFIG
# =========================
DEFAULT_NOTIONAL = 7000
EXTENDED_LIMIT_OFFSET = 0.005

# =========================
# STATE (TP CONTROL)
# =========================
last_signal = {}
tp1_armed = {}

# =========================
# SESSION CHECK
# =========================
def is_regular_hours():
    eastern = pytz.timezone("US/Eastern")
    now = datetime.now(eastern).time()
    return time(9, 30) <= now <= time(16, 0)

# =========================
# POSITION
# =========================
def get_position(symbol):
    try:
        return api.get_position(symbol)
    except:
        return None

# =========================
# PRICE
# =========================
def get_quote(symbol):
    q = api.get_latest_quote(symbol)
    return float(q.ap), float(q.bp)

# =========================
# SIZE CALC
# =========================
def calc_qty(notional, price):
    if price <= 0:
        return 0
    return int(notional / price)

# =========================
# HELPERS
# =========================
def sell_qty(symbol, qty):
    if qty <= 0:
        return

    api.submit_order(
        symbol=symbol,
        qty=qty,
        side="sell",
        type="market",
        time_in_force="day",
        reduce_only=True
    )

def close_position(symbol):
    try:
        api.close_position(symbol)
    except:
        pass

def already_fired(symbol, signal):
    key = f"{symbol}:{signal}"
    now = pytime.time()

    if key in last_signal and now - last_signal[key] < 2:
        return True

    last_signal[key] = now
    return False

# =========================
# WEBHOOK
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)

        print("WEBHOOK:", data, flush=True)

        symbol = data.get("ticker") or data.get("symbol")
        signal = (data.get("signal") or "").upper()

        if not symbol or not signal:
            return jsonify({"error": "invalid payload"}), 400

        position = get_position(symbol)
        is_long = position is not None
        regular = is_regular_hours()

        # =========================
        # DUPLICATE GUARD
        # =========================
        if already_fired(symbol, signal):
            return jsonify({"status": "duplicate_ignored"}), 200

        # =========================
        # OPEN LONG
        # =========================
        if signal == "OPEN_LONG":

            if is_long:
                return jsonify({"status": "already_in_position"}), 200

            ask, _ = get_quote(symbol)

            qty = calc_qty(DEFAULT_NOTIONAL, ask)

            if qty <= 0:
                return jsonify({"error": "qty_calc_failed"}), 400

            if regular:
                api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="buy",
                    type="market",
                    time_in_force="day"
                )
                return jsonify({"status": "long_market", "qty": qty})

            limit_price = round(ask * (1 + EXTENDED_LIMIT_OFFSET), 2)

            api.submit_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                type="limit",
                time_in_force="day",
                limit_price=limit_price,
                extended_hours=True
            )

            return jsonify({
                "status": "long_limit_extended",
                "qty": qty,
                "limit_price": limit_price
            })

        # =========================
        # FULL EXIT GROUP
        # =========================
        if signal in ["CLOSE_LONG", "EXIT_LONG", "BE", "SL"]:

            if not is_long:
                return jsonify({"status": "no_position"}), 200

            close_position(symbol)
            tp1_armed[symbol] = False

            return jsonify({"status": "position_closed"}), 200

        # =========================
        # TP1_SL (STATE CHANGE ONLY)
        # =========================
        if signal == "TP1_SL":
            tp1_armed[symbol] = True
            return jsonify({"status": "tp1_stop_armed"}), 200

        # =========================
        # TAKE PROFITS (DYNAMIC POSITION BASED)
        # =========================
        if not is_long:
            return jsonify({"status": "no_position"}), 200

        qty = float(position.qty)

        if signal == "TP1":
            sell_qty(symbol, int(qty * 0.25))

        elif signal == "TP2":
            sell_qty(symbol, int(qty * 0.20))

        elif signal == "TP3":
            sell_qty(symbol, int(qty * 0.10))

        elif signal == "TP4":
            sell_qty(symbol, int(qty * 0.10))

        else:
            return jsonify({"error": "unknown signal"}), 400

        return jsonify({"status": "tp_executed", "signal": signal}), 200

    except Exception as e:
        print("ERROR:", str(e), flush=True)
        return jsonify({"error": str(e)}), 500


# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
