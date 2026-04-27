from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os

app = Flask(__name__)

# === DEBUG ENV VARS ===

print("KEY:", os.getenv("APCA_API_KEY_ID"))
print("SECRET:", os.getenv("APCA_API_SECRET_KEY"))

# === ALPACA SETUP ===
api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://paper-api.alpaca.markets"  # change to live later
)

# === WEBHOOK ===
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # --- DEBUG ---
        print("RAW:", request.data)

        data = request.get_json(force=True, silent=True)
        print("PARSED:", data)

        if not data:
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400

        # --- EXTRACT FIELDS ---
        symbol = data.get("symbol")
        action = data.get("action")

        try:
            qty = int(float(data.get("quantity", 0)))
        except:
            qty = 0

        try:
            limit_price = float(data.get("limit_price"))
        except:
            return jsonify({"status": "error", "message": "Invalid limit_price", "data": data}), 400

        order_type = data.get("type", "limit")
        tif = data.get("time_in_force", "day")
        extended = data.get("extended_hours", True)

        # --- VALIDATION ---
        if not symbol or not action or qty <= 0:
            return jsonify({
                "status": "error",
                "message": "Missing required fields",
                "data": data
            }), 400

        # === APPLY EXTENDED HOURS BUFFER ===
        if action == "buy":
            limit_price *= 1.008   # +0.8%
        elif action == "sell":
            limit_price *= 0.992   # -0.8%

        # --- POSITION CHECK ---
        positions = {p.symbol: p for p in api.list_positions()}
        position = positions.get(symbol)

        if action == "buy" and position:
            return jsonify({"status": "skipped", "reason": "already in position"})

        if action == "sell" and not position:
            return jsonify({"status": "skipped", "reason": "no position"})

        # --- SUBMIT ORDER ---
        order = api.submit_order(
            symbol=symbol,
            qty=qty,
            side=action,
            type=order_type,
            time_in_force=tif,
            limit_price=round(limit_price, 2),
            extended_hours=extended
        )

        return jsonify({
            "status": "success",
            "symbol": symbol,
            "side": action,
            "qty": qty,
            "limit_price": limit_price,
            "order_id": order.id
        })

    except Exception as e:
        print("ALPACA ERROR:", str(e))   # <-- THIS LINE
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


# === HEALTH CHECK ===
@app.route('/')
def home():
    return "Alpaca bot running"
