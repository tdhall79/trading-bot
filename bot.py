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
# STATE
# =========================
last_signal = {}
tp1_armed = {}

# =========================
# HEALTH CHECK (REQUIRED FOR RENDER)
# =========================
@app.route("/", methods=["GET"])
def home():
    return "ALIVE", 200

# =========================
# SESSION
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
        pos = api.get_position(symbol)
        return float(pos.qty)
    except:
        return 0

# =========================
# PRICE
# =========================
def get_quote(symbol):
    q = api.get_latest_quote(symbol)
    return float(q.ap), float(q.bp)

# =========================
# SIZE
# =========================
def calc_qty(notional, price):
    if price <= 0:
        return 0
    return int(notional / price)

# =========================
# ORDERS
# =========================
def sell_qty(symbol, qty):
    if qty <= 0:
        return
    try:
        api.submit_order(
            symbol=symbol,
            qty=qty,
            side="sell",
            type="market",
            time_in_force="day",
            reduce_only=True
        )
    except Exception as e:
        print("SELL ERROR:", str(e), flush=True)

def close_position(symbol):
    try:
        api.close_position(symbol)
    except Exception as e:
        print("CLOSE ERROR:", str(e), flush=True)

# =========================
# SIGNAL NORMALIZER
# =========================
def normalize_signal(raw):
    if not raw:
        return ""

    s = str(raw).upper().strip()

    for ch in [" ", "-", "_", "|"]:
        s = s.replace(ch, "")

    print("NORMALIZED RAW:", s, flush=True)

    # ENTRY
    if "LONG" == s:
        return "OPEN_LONG"
    if "ENTRY" in s:
        return "OPEN_LONG"

    # EXIT
    if "EXIT" in s or "CLOSE" in s:
        return "EXIT_LONG"

    # STOP / BE
    if "SL" in s or "STOP" in s:
        return "SL"

    if "BE" in s or "BREAKEVEN" in s:
        return "BE"

    # TP LEVELS
    if "TP1" in s or "TAKEPROFIT1" in s:
        return "TP1"
    if "TP2" in s or "TAKEPROFIT2" in s:
        return "TP2"
    if "TP3" in s or "TAKEPROFIT3" in s:
        return "TP3"
    if "TP4" in s or "TAKEPROFIT4" in s:
        return "TP4"

    return ""

# =========================
# DUPLICATE GUARD
# =========================
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
        data = request.get_json(force=True, silent=True)

        print("RAW WEBHOOK:", data, flush=True)

        if not data:
            return jsonify({"status": "empty"}), 200

        symbol = data.get("ticker") or data.get("symbol")
        raw_signal = data.get("signal")

        signal = normalize_signal(raw_signal)

        print("PARSED:", symbol, raw_signal, "->", signal, flush=True)

        if not symbol or not signal:
            return jsonify({"status": "bad_payload"}), 200

        if already_fired(symbol, signal):
            return jsonify({"status": "duplicate"}), 200

        qty_position = get_position(symbol)
        is_long = qty_position > 0
        regular = is_regular_hours()

        # =========================
        # ENTRY
        # =========================
        if signal == "OPEN_LONG":

            if is_long:
                return jsonify({"status": "already_in_position"}), 200

            ask, _ = get_quote(symbol)
            qty = calc_qty(DEFAULT_NOTIONAL, ask)

            if qty <= 0:
                return jsonify({"status": "qty_fail"}), 200

            if regular:
                api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="buy",
                    type="market",
                    time_in_force="day"
                )
            else:
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

            return jsonify({"status": "entry_sent"}), 200

        # =========================
        # EXIT GROUP
        # =========================
        if signal in ["EXIT_LONG", "SL", "BE"]:

            close_position(symbol)
            tp1_armed[symbol] = False

            return jsonify({"status": "exit_sent"}), 200

        # =========================
        # TP LOGIC
        # =========================
        if qty_position <= 0:
            return jsonify({"status": "no_position"}), 200

        qty = float(qty_position)

        if signal == "TP1":
            sell_qty(symbol, int(qty * 0.25))
        elif signal == "TP2":
            sell_qty(symbol, int(qty * 0.20))
        elif signal == "TP3":
            sell_qty(symbol, int(qty * 0.10))
        elif signal == "TP4":
            sell_qty(symbol, int(qty * 0.10))
        else:
            return jsonify({"status": "ignored"}), 200

        return jsonify({"status": "tp_sent"}), 200

    except Exception as e:
        print("FATAL ERROR:", str(e), flush=True)
        return jsonify({"status": "error_handled"}), 200


# =========================
# RUN (RENDER SAFE)
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
