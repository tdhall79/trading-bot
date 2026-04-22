from flask import Flask, request, jsonify
import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

app = Flask(__name__)

# =========================
# ALPACA SETUP (NEW SDK)
# =========================
client = TradingClient(
    api_key=os.environ.get("ALPACA_API_KEY"),
    secret_key=os.environ.get("ALPACA_SECRET"),
    paper=False  # set True if paper trading
)

# =========================
# ROUTES
# =========================
@app.route("/")
def home():
    return "Alpaca bot running"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print(f"Incoming: {data}", flush=True)

    try:
        symbol = data.get("symbol")
        action = data.get("action")
        qty = float(data.get("quantity", 0))
        order_type = data.get("type", "limit")  # default safer
        limit_price = data.get("limit_price")
        tif = data.get("time_in_force", "day")
        extended = data.get("extended_hours", False)

        # =========================
        # VALIDATION
        # =========================
        if not symbol or not action:
            return jsonify({"error": "Missing symbol or action"}), 400

        if qty <= 0:
            return jsonify({"error": "Invalid quantity"}), 400

        if order_type == "limit" and not limit_price:
            return jsonify({"error": "Missing limit_price"}), 400

        side = OrderSide.BUY if action == "buy" else OrderSide.SELL
        tif_enum = TimeInForce.GTC if tif == "gtc" else TimeInForce.DAY

        # =========================
        # CREATE ORDER
        # =========================
        if order_type == "limit":
            order = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side,
                time_in_force=tif_enum,
                limit_price=float(limit_price),
                extended_hours=extended
            )
        else:
            order = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side,
                time_in_force=tif_enum
            )

        # =========================
        # SEND ORDER
        # =========================
        response = client.submit_order(order)
        print(f"Order sent: {response}", flush=True)

        return jsonify({"status": "success"})

    except Exception as e:
        print(f"ERROR: {str(e)}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# =========================
# RUN (RENDER)
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)