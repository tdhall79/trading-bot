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

# ===== CONFIG =====
COOLDOWN_SECONDS = 5
RETRY_DELAY = 3  # seconds before checking fill
MAX_RETRY = 1

last_signal = {}


def get_position(symbol):
    try:
        return api.get_position(symbol)
    except:
        return None


def is_long(symbol):
    return get_position(symbol) is not None


def get_prices(symbol):
    quote = api.get_latest_quote(symbol)
    ask = float(quote.ap)
    bid = float(quote.bp)
    mid = (ask + bid) / 2
    spread = ask - bid
    spread_pct = spread / mid if mid > 0 else 0
    return ask, bid, spread_pct


def place_limit(symbol, qty, side, price):
    return api.submit_order(
        symbol=symbol,
        qty=qty,
        side=side,
        type="limit",
        time_in_force="day",
        limit_price=round(price, 2),
        extended_hours=True
    )


def wait_and_retry(order_id, symbol, qty, side, aggressive_price):
    time.sleep(RETRY_DELAY)

    order = api.get_order(order_id)

    if order.status != "filled":
        print("Retrying with aggressive price...", flush=True)

        # cancel old
        api.cancel_order(order_id)

        # resend more aggressive
        return place_limit(symbol, qty, side, aggressive_price)

    return order


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

        if last:
            if (now - last["time"] < COOLDOWN_SECONDS) and (last["signal"] != signal):
                return jsonify({"status": "flip_blocked"}), 200

        last_signal[symbol] = {"signal": signal, "time": now}

        ask, bid, spread_pct = get_prices(symbol)

        long_state = is_long(symbol)

        # ===== LONG ENTRY =====
        if signal == "LONG":
            if long_state:
                return jsonify({"status": "already_long"}), 200

            # adaptive pricing
            if spread_pct > 0.005:  # illiquid
                limit_price = ask * 1.02
                aggressive_price = ask * 1.04
            else:
                limit_price = ask * 1.001
                aggressive_price = ask * 1.005

            order = place_limit(symbol, qty, "buy", limit_price)

            # retry if needed
            order = wait_and_retry(order.id, symbol, qty, "buy", aggressive_price)

            return jsonify({
                "status": "long_order_sent",
                "limit_price": limit_price,
                "spread_pct": spread_pct
            })

        # ===== EXIT LONG =====
        if signal == "EXIT LONG":
            if not long_state:
                return jsonify({"status": "no_position"}), 200

            if spread_pct > 0.005:
                limit_price = bid * 0.98
                aggressive_price = bid * 0.96
            else:
                limit_price = bid * 0.999
                aggressive_price = bid * 0.995

            order = place_limit(symbol, qty, "sell", limit_price)

            order = wait_and_retry(order.id, symbol, qty, "sell", aggressive_price)

            return jsonify({
                "status": "exit_order_sent",
                "limit_price": limit_price,
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
