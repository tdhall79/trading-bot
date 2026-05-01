from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os
import time
import hashlib

# =====================================================
# APP (MUST BE FIRST BEFORE ANY ROUTES)
# =====================================================
app = Flask(__name__)

# =====================================================
# ALPACA
# =====================================================
api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://api.alpaca.markets"
)

# =====================================================
# CONFIG
# =====================================================
MAX_AGE = 300
COOLDOWN = 30
MIN_FLIP_GAP = 2
USE_MARKET_ORDERS = True

STATE = {}

# =====================================================
# HELPERS
# =====================================================
def now():
    return time.time()

def get_position(symbol):
    try:
        return api.get_position(symbol)
    except:
        return None

def get_open_order(symbol):
    orders = api.list_orders(status="open", symbols=[symbol])
    return orders[0] if orders else None

def cancel_open_order(symbol):
    order = get_open_order(symbol)
    if order:
        api.cancel_order(order.id)

def get_prices(symbol):
    q = api.get_latest_quote(symbol)
    ask = float(q.ap)
    bid = float(q.bp)
    mid = (ask + bid) / 2
    spread_pct = (ask - bid) / mid if mid > 0 else 0
    return ask, bid, spread_pct

def make_event_id(data):
    if data.get("event_id"):
        return data["event_id"]
    raw = f"{data.get('symbol')}|{data.get('signal')}|{data.get('time')}"
    return hashlib.sha256(raw.encode()).hexdigest()

def is_stale(event_time):
    return (now() - event_time / 1000) > MAX_AGE

# =====================================================
# WEBHOOK
# =====================================================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        print("WEBHOOK RECEIVED:", data, flush=True)

        # -----------------------------
        # CLEAN INPUT
        # -----------------------------
        symbol = data.get("symbol", "").strip().upper()
        signal = (data.get("signal") or "").strip().upper()
        qty = float(data.get("qty", 0))
        event_time = int(data.get("time", 0))

        if signal not in ["LONG", "EXIT LONG"]:
            return jsonify({"error": "invalid signal"}), 400

        if not symbol:
            return jsonify({"error": "missing symbol"}), 400

        if qty <= 0:
            return jsonify({"error": "invalid qty"}), 400

        if not event_time:
            return jsonify({"error": "missing time"}), 400

        # -----------------------------
        # STATE INIT
        # -----------------------------
        if symbol not in STATE:
            STATE[symbol] = {
                "last_event_time": 0,
                "last_signal": None,
                "last_trade_time": 0,
                "last_event_id": None
            }

        state = STATE[symbol]

        # -----------------------------
        # FILTERS
        # -----------------------------
        if is_stale(event_time):
            return jsonify({"status": "stale_ignored"}), 200

        if event_time < state["last_event_time"]:
            return jsonify({"status": "out_of_order"}), 200

        event_id = make_event_id(data)
        if event_id == state["last_event_id"]:
            return jsonify({"status": "duplicate"}), 200

        # flip protection (critical fix for AlgoPro noise)
        time_diff = (event_time - state["last_event_time"]) / 1000
        if (
            state["last_signal"] is not None and
            signal != state["last_signal"] and
            time_diff < MIN_FLIP_GAP
        ):
            print("FLIP IGNORED:", state["last_signal"], "->", signal, flush=True)
            return jsonify({"status": "flip_ignored"}), 200

        # cooldown
        if now() - state["last_trade_time"] < COOLDOWN:
            return jsonify({"status": "cooldown"}), 200

        # update state
        state["last_event_time"] = event_time
        state["last_event_id"] = event_id
        state["last_signal"] = signal

        # -----------------------------
        # MARKET DATA
        # -----------------------------
        ask, bid, spread = get_prices(symbol)
        position = get_position(symbol)
        is_long = position is not None

        print(f"{symbol} | {signal} | position={is_long}", flush=True)

        # =====================================================
        # LONG ENTRY
        # =====================================================
        if signal == "LONG":

            if is_long:
                return jsonify({"status": "already_in_position"}), 200

            cancel_open_order(symbol)

            if USE_MARKET_ORDERS:
                api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="buy",
                    type="market",
                    time_in_force="day"
                )
            else:
                price = ask * 1.001
                api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="buy",
                    type="limit",
                    time_in_force="day",
                    limit_price=round(price, 2)
                )

            state["last_trade_time"] = now()
            return jsonify({"status": "LONG executed"})

        # =====================================================
        # EXIT LONG
        # =====================================================
        if signal == "EXIT LONG":

            if not is_long:
                return jsonify({"status": "no_position"}), 200

            cancel_open_order(symbol)

            qty_to_sell = abs(float(position.qty))

            if USE_MARKET_ORDERS:
                api.submit_order(
                    symbol=symbol,
                    qty=qty_to_sell,
                    side="sell",
                    type="market",
                    time_in_force="day"
                )
            else:
                price = bid * 0.999
                api.submit_order(
                    symbol=symbol,
                    qty=qty_to_sell,
                    side="sell",
                    type="limit",
                    time_in_force="day",
                    limit_price=round(price, 2)
                )

            state["last_trade_time"] = now()
            return jsonify({"status": "EXIT executed"})

    except Exception as e:
        print("ERROR:", str(e), flush=True)
        return jsonify({"error": str(e)}), 500

# =====================================================
# HEALTH CHECK
# =====================================================
@app.route("/")
def home():
    return "Bot running"

# =====================================================
# ENTRY POINT
# =====================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

@app.route("/ping")
def ping():
    return "PING OK"
