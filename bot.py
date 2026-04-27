print("RAW:", request.data)
print("JSON:", request.get_json(force=True, silent=True))

from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os

# ✅ CREATE APP FIRST
app = Flask(__name__)

# ✅ THEN SETUP ALPACA
api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://paper-api.alpaca.markets"
)

# ✅ THEN ROUTES
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)

        if not data:
            return jsonify({"status": "error", "message": "No JSON received"}), 400

        symbol = data.get("symbol")
        action = data.get("action")

        try:
            qty = int(float(data.get("quantity", 0)))
        except:
            qty = 0

        try:
            limit_price = float(data.get("limit_price")) if data.get("limit_price") is not None else None
        except:
            limit_price = None

        order_type = data.get("type", "limit")
        tif = data.get("time_in_force", "day")
        extended = data.get("extended_hours", True)

        if not symbol or not action or qty <= 0:
            return jsonify({"status": "error", "message": "Invalid payload", "received": data}), 400

        positions = {p.symbol: p for p in api.list_positions()}
        position = positions.get(symbol)

        if action == "buy" and position:
            return jsonify({"status": "skipped", "reason": "already in position"})

        if action == "sell" and not position:
            return jsonify({"status": "skipped", "reason": "no position"})

        order = api.submit_order(
            symbol=symbol,
            qty=qty,
            side=action,
            type=order_type,
            time_in_force=tif,
            limit_price=limit_price,
            extended_hours=extended
        )

        return jsonify({"status": "success", "order_id": order.id})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route('/')
def home():
    return "Bot running" 
