from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os

app = Flask(__name__)

api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://api.alpaca.markets"
)


# =========================
# HELPERS
# =========================

def get_position(symbol):
    try:
        return api.get_position(symbol)
    except:
        return None


def get_quote(symbol):
    q = api.get_latest_quote(symbol)
    ask = float(q.ap)
    bid = float(q.bp)
    return ask, bid


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

        # optional controls
        offset = float(data.get("limit_offset", 0.002))  # 0.2% default
        extended = bool(data.get("extended_hours", True))

        if not symbol or not signal or qty <= 0:
            return jsonify({"error": "invalid payload"}), 400

        ask, bid = get_quote(symbol)

        position = get_position(symbol)
        is_long = position is not None

        # =====================
        # LONG ENTRY
        # =====================
        if signal == "LONG":

            if is_long:
                return jsonify({"status": "already_long"}), 200

            # marketable limit (slightly above ask)
            limit_price = ask * (1 + offset)

            order = api.submit_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                type="limit",
                time_in_force="day",
                limit_price=round(limit_price, 2),
                extended_hours=extended
            )

            return jsonify({
                "status": "long_submitted",
                "price": limit_price
            })

        # =====================
        # EXIT LONG
        # =====================
        if signal == "EXIT LONG":

            if not is_long:
                return jsonify({"status": "no_position"}), 200

            # marketable limit (slightly below bid)
            limit_price = bid * (1 - offset)

            order = api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="limit",
                time_in_force="day",
                limit_price=round(limit_price, 2),
                extended_hours=extended
            )

            return jsonify({
                "status": "exit_submitted",
                "price": limit_price
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