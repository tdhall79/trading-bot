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

# === FLIP PROTECTION MEMORY ===
last_signal = {}  # {symbol: {"signal": str, "time": float}}

COOLDOWN_SECONDS = 5


def get_position(symbol):
    try:
        return api.get_position(symbol)
    except:
        return None


def is_long(symbol):
    return get_position(symbol) is not None


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)

        print("WEBHOOK RECEIVED:", data, flush=True)

        symbol = data.get("symbol")
        signal = (data.get("signal") or "").upper()
        qty = float(data.get("qty", 0))
        offset = float(data.get("limit_offset", 0.005))

        if not symbol or not signal or qty <= 0:
            return jsonify({"error": "invalid payload"}), 400

        # =========================
        # FLIP / DUPLICATE FILTER
        # =========================
        now = time.time()
        last = last_signal.get(symbol)

        if last:
            same_time_window = (now - last["time"]) < COOLDOWN_SECONDS
            opposite_signal = last["signal"] != signal

            if same_time_window and opposite_signal:
                return jsonify({
                    "status": "ignored_flip_protection",
                    "symbol": symbol,
                    "signal": signal
                }), 200

        last_signal[symbol] = {"signal": signal, "time": now}

        # =========================
        # GET MARKET DATA (bid/ask)
        # =========================
        quote = api.get_latest_quote(symbol)

        ask = float(quote.ap) if quote.ap else None
        bid = float(quote.bp) if quote.bp else None

        if not ask or not bid:
            return jsonify({"error": "no quote data"}), 400

        long_state = is_long(symbol)

        # =========================
        # LONG ENTRY
        # =========================
        if signal == "LONG":
            if not long_state:

                limit_price = ask * (1 + offset)

                api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="buy",
                    type="limit",
                    time_in_force="day",
                    limit_price=round(limit_price, 2),
                    extended_hours=False
                )

                return jsonify({
                    "status": "long_opened",
                    "symbol": symbol,
                    "qty": qty,
                    "limit_price": limit_price
                })

            return jsonify({"status": "already_long"}), 200

        # =========================
        # EXIT LONG
        # =========================
        if signal == "EXIT LONG":
            if long_state:

                limit_price = bid * (1 - offset)

                api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="sell",
                    type="limit",
                    time_in_force="day",
                    limit_price=round(limit_price, 2),
                    extended_hours=False
                )

                return jsonify({
                    "status": "long_closed",
                    "symbol": symbol,
                    "qty": qty,
                    "limit_price": limit_price
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
