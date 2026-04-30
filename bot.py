from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os
import time

app = Flask(__name__)

api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://api.alpaca.markets"
)

# Track last signal (flip protection)
last_signal = {}
COOLDOWN = 3


# =========================
# HELPERS
# =========================

def get_position(symbol):
    try:
        return api.get_position(symbol)
    except:
        return None


def get_open_order(symbol):
    orders = api.list_orders(status="open", symbols=[symbol])
    return orders[0] if orders else None


def wait_for_cancel(order_id):
    for _ in range(10):
        time.sleep(0.5)
        o = api.get_order(order_id)
        if o.status in ["canceled", "expired", "rejected"]:
            return True
    return False


def replace_order(symbol, qty, side, price):
    existing = get_open_order(symbol)

    if existing:
        api.cancel_order(existing.id)

        if not wait_for_cancel(existing.id):
            print("Cancel failed, skipping replace", flush=True)
            return None

    return api.submit_order(
        symbol=symbol,
        qty=qty,
        side=side,
        type="limit",
        time_in_force="day",
        limit_price=round(price, 2),
        extended_hours=True
    )


def get_prices(symbol):
    q = api.get_latest_quote(symbol)
    ask = float(q.ap)
    bid = float(q.bp)
    mid = (ask + bid) / 2
    spread = ask - bid
    spread_pct = spread / mid if mid > 0 else 0
    return ask, bid, spread_pct


# =========================
# WEBHOOK
# =========================

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)

        print("WEBHOOK:", data, flush=True)

        symbol = data.get("symbol")
        signal = (data.get("signal") or "").upper()
        qty = float(data.get("qty", 0))

        if not symbol or not signal or qty <= 0:
            return jsonify({"error": "invalid payload"}), 400

        # ===== FLIP PROTECTION =====
        now = time.time()
        last = last_signal.get(symbol)

        if last and (now - last["time"] < COOLDOWN) and (last["signal"] != signal):
            return jsonify({"status": "flip_blocked"}), 200

        last_signal[symbol] = {"signal": signal, "time": now}

        # ===== MARKET DATA =====
        ask, bid, spread_pct = get_prices(symbol)

        # ===== POSITION STATE =====
        position = get_position(symbol)
        is_long = position is not None

        # =====================
        # LONG ENTRY
        # =====================
        if signal == "LONG":

            if is_long:
                return jsonify({"status": "already_long"}), 200

            # adaptive aggressiveness
            if spread_pct > 0.005:
                price = ask * 1.02
            else:
                price = ask * 1.001

            order = replace_order(symbol, qty, "buy", price)

            return jsonify({
                "status": "long_order_active",
                "price": price,
                "spread_pct": spread_pct
            })

        # =====================
        # EXIT LONG
        # =====================
        if signal == "EXIT LONG":

            if not is_long:
                return jsonify({"status": "no_position"}), 200

            if spread_pct > 0.005:
                price = bid * 0.98
            else:
                price = bid * 0.999

            order = replace_order(symbol, qty, "sell", price)

            return jsonify({
                "status": "exit_order_active",
                "price": price,
                "spread_pct": spread_pct
            })

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
