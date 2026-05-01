from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os
import time
import json
import hashlib

app = Flask(__name__)

api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://api.alpaca.markets"
)

# =========================
# CONFIG
# =========================
STATE_FILE = "state.json"
MAX_AGE = 900  # 15 min (safe default)
WARMUP = 5     # seconds after restart

START_TIME = time.time()

# =========================
# STATE (persistent)
# =========================
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump(STATE, f)

STATE = load_state()

# =========================
# HELPERS
# =========================
def now():
    return time.time()

def get_position(symbol):
    try:
        return api.get_position(symbol)
    except:
        return None

def cancel_open_orders(symbol):
    orders = api.list_orders(status="open", symbols=[symbol])
    for o in orders:
        api.cancel_order(o.id)

def get_prices(symbol):
    q = api.get_latest_quote(symbol)
    ask = float(q.ap)
    bid = float(q.bp)
    mid = (ask + bid) / 2
    spread = ask - bid
    spread_pct = spread / mid if mid > 0 else 0
    return ask, bid, spread_pct

def make_event_id(data):
    raw = f"{data.get('symbol')}|{data.get('signal')}|{data.get('time',0)}"
    return hashlib.sha256(raw.encode()).hexdigest()

def is_stale(event_time):
    return (now() - event_time / 1000) > MAX_AGE

# =========================
# WEBHOOK
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        print("RAW:", request.data, flush=True)
        print("PARSED:", data, flush=True)

        symbol = data.get("symbol")
        signal = (data.get("signal") or "").upper()
        qty = float(data.get("qty", 0))
        offset = float(data.get("limit_offset", 0.01))

        # fallback if no time provided
        event_time = data.get("time")
        if not event_time:
            event_time = int(time.time() * 1000)
            print("⚠️ Missing time, using server time", flush=True)

        # basic validation
        if not symbol or signal not in ["LONG", "EXIT LONG"]:
            return jsonify({"error": "invalid payload"}), 400

        # warmup protection (after restart)
        if now() - START_TIME < WARMUP:
            print("WARMUP BLOCK", flush=True)
            return jsonify({"status": "warming_up"}), 200

        # init symbol state
        if symbol not in STATE:
            STATE[symbol] = {
                "last_event_time": 0,
                "last_event_id": None
            }

        state = STATE[symbol]

        print("STATE BEFORE:", state, flush=True)

        # stale filter (log, don’t silently kill)
        if is_stale(event_time):
            print("⚠️ STALE SIGNAL", flush=True)

        # ordering
        if event_time < state["last_event_time"]:
            print("IGNORED: out of order", flush=True)
            return jsonify({"status": "out_of_order"}), 200

        # dedup
        event_id = make_event_id(data)
        if event_id == state["last_event_id"]:
            print("IGNORED: duplicate", flush=True)
            return jsonify({"status": "duplicate"}), 200

        # update state
        state["last_event_time"] = event_time
        state["last_event_id"] = event_id
        save_state()

        # market + position
        ask, bid, spread_pct = get_prices(symbol)
        position = get_position(symbol)
        is_long = position is not None

        print(f"{symbol} | {signal} | pos={is_long} | spread={spread_pct:.4f}", flush=True)

        # =====================
        # LONG
        # =====================
        if signal == "LONG":
            if is_long:
                print("SKIP: already long", flush=True)
                return jsonify({"status": "already_long"}), 200

            cancel_open_orders(symbol)

            price = ask * (1 + offset if spread_pct <= 0.005 else 1 + offset * 2)

            print(f"BUY → {symbol} qty={qty} price={price}", flush=True)

            api.submit_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                type="limit",
                time_in_force="day",
                limit_price=round(price, 2),
                extended_hours=True
            )

            return jsonify({"status": "long_sent"}), 200

        # =====================
        # EXIT
        # =====================
        if signal == "EXIT LONG":
            if not is_long:
                print("SKIP: no position", flush=True)
                return jsonify({"status": "no_position"}), 200

            cancel_open_orders(symbol)

            actual_qty = abs(float(position.qty))

            price = bid * (1 - offset if spread_pct <= 0.005 else 1 - offset * 2)

            print(f"SELL → {symbol} qty={actual_qty} price={price}", flush=True)

            api.submit_order(
                symbol=symbol,
                qty=actual_qty,
                side="sell",
                type="limit",
                time_in_force="day",
                limit_price=round(price, 2),
                extended_hours=True
            )

            return jsonify({"status": "exit_sent"}), 200

        return jsonify({"status": "ignored"}), 200

    except Exception as e:
        print("ERROR:", str(e), flush=True)
        return jsonify({"error": str(e)}), 500


@app.route("/")
def home():
    return "Bot running"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
