from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os

app = Flask(__name__)

api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://api.alpaca.markets"
)


def get_position(symbol):
    try:
        return api.get_position(symbol)
    except:
        return None


def open_position(symbol, qty, limit_price):
    api.submit_order(
        symbol=symbol,
        qty=qty,
        side="buy",
        type="limit",
        time_in_force="day",
        limit_price=round(limit_price, 2),
        extended_hours=True
    )


def close_position(symbol, qty):
    api.submit_order(
        symbol=symbol,
        qty=qty,
        side="sell",
        type="limit",
        time_in_force="day",
        extended_hours=True
    )


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)

        print("WEBHOOK RECEIVED:", data, flush=True)

        symbol = data.get("symbol")
        signal = (data.get("signal") or "").upper()
        qty = float(data.get("qty", 0))
        offset = float(data.get("limit_offset", 0.01))

        if not symbol or not signal or qty <= 0:
            return jsonify({"error": "invalid payload"}), 400

        price = float(api.get_latest_trade(symbol).price)
        position = get_position(symbol)
        is_long = position is not None

        # =====================
        # LONG ENTRY
        # =====================
        if signal == "LONG":
            if not is_long:
                limit_price = price * (1 - offset)

                open_position(symbol, qty, limit_price)

                return jsonify({
                    "status": "long_opened",
                    "symbol": symbol,
                    "qty": qty
                })

            return jsonify({"status": "already_long"}), 200

        # =====================
        # EXIT LONG
        # =====================
        if signal == "EXIT LONG":
            if is_long:
                close_position(symbol, qty)

                return jsonify({
                    "status": "long_closed",
                    "symbol": symbol,
                    "qty": qty
                })

            return jsonify({"status": "no_position"}), 200

        return jsonify({"status": "ignored_signal"}), 200

    except Exception as e:
        print("ERROR:", str(e), flush=True)
        return jsonify({"error": str(e)}), 500


@app.route("/")
def home():
    return "Bot running"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
