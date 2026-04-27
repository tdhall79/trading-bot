from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os

app = Flask(__name__)

api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://paper-api.alpaca.markets"
)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(force=True)

    symbol = data["symbol"]
    action = data["action"]
    qty = data["quantity"]

    try:
        # === POSITION CHECK ===
        positions = {p.symbol: p for p in api.list_positions()}
        position = positions.get(symbol)

        # Prevent duplicate buys
        if action == "buy" and position:
            return jsonify({"status": "skipped", "reason": "already in position"})

        # Prevent selling nothing
        if action == "sell" and not position:
            return jsonify({"status": "skipped", "reason": "no position"})

        # === SUBMIT ORDER ===
        order = api.submit_order(
            symbol=symbol,
            qty=qty,
            side=action,
            type=data.get("type", "limit"),
            time_in_force=data.get("time_in_force", "day"),
            limit_price=data.get("limit_price"),
            extended_hours=data.get("extended_hours", True)
        )

        return jsonify({
            "status": "filled",
            "symbol": symbol,
            "side": action,
            "qty": qty,
            "order_id": order.id
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route('/')
def home():
    return "Alpaca webhook live"
