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


def close_position(symbol):
    try:
        pos = api.get_position(symbol)
        api.submit_order(
            symbol=symbol,
            qty=pos.qty,
            side="sell",
            type="market",
            time_in_force="gtc"
        )
    except:
        pass


def open_position(symbol, risk=0.1):
    account = api.get_account()
    equity = float(account.equity)

    price = float(api.get_latest_trade(symbol).price)
    qty = (equity * risk) / price

    api.submit_order(
        symbol=symbol,
        qty=round(qty, 6),
        side="buy",
        type="market",
        time_in_force="gtc"
    )


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)

        print("WEBHOOK RECEIVED:", data, flush=True)

        symbol = data.get("symbol")
        signal = (data.get("signal") or "").upper()
        risk = float(data.get("risk", 0.1))

        if not symbol or not signal:
            return jsonify({"error": "missing fields"}), 400

        position = get_position(symbol)
        is_long = position is not None

        # BUY = ignore (intent only)
        if signal == "BUY":
            return jsonify({"status": "ignored"}), 200

        # LONG = entry
        if signal == "LONG":
            if not is_long:
                open_position(symbol, risk)
            return jsonify({"status": "long_executed"}), 200

        # SELL = exit
        if signal == "SELL":
            if is_long:
                close_position(symbol)
            return jsonify({"status": "closed"}), 200

        return jsonify({"status": "no_action"}), 200

    except Exception as e:
        print("ERROR:", str(e), flush=True)
        return jsonify({"error": str(e)}), 500


@app.route('/')
def home():
    return "Bot running"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
