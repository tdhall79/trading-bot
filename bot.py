from flask import Flask, request, jsonify
import os
import ccxt

app = Flask(__name__)

# =========================
# CONFIG
# =========================
MODE = "LIVE"
ALLOCATION = 0.75  # 75%

# =========================
# KRAKEN SETUP
# =========================
kraken = ccxt.kraken({
    "apiKey": os.environ.get("KRAKEN_API_KEY"),
    "secret": os.environ.get("KRAKEN_SECRET"),
    "enableRateLimit": True
})

# Map TradingView symbols → Kraken pairs
SYMBOL_MAP = {
    "BTCUSD": "BTC/USD",
    "SOLUSD": "SOL/USD"
}

# =========================
# HELPERS
# =========================
def get_balance(currency):
    balance = kraken.fetch_balance()
    return balance["total"].get(currency, 0)

def get_price(pair):
    ticker = kraken.fetch_ticker(pair)
    return ticker["last"]

# =========================
# ROUTES
# =========================
@app.route("/", methods=["GET"])
def home():
    return "Kraken bot is live"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print(f"Incoming: {data}", flush=True)

    action = data.get("action")   # "buy" or "sell"
    symbol = data.get("symbol")   # "BTCUSD" or "SOLUSD"

    try:
        if symbol in SYMBOL_MAP:
            pair = SYMBOL_MAP[symbol]

            # 🔥 ALWAYS use live Kraken price
            price = get_price(pair)

            usd_balance = get_balance("USD")
            allocation_value = usd_balance * ALLOCATION

            base_asset = pair.split("/")[0]  # BTC or SOL

            # =========================
            # BUY
            # =========================
            if action == "buy":
                qty = allocation_value / price
                qty = float(f"{qty:.8f}")  # precision safety

                if qty > 0:
                    kraken.create_market_buy_order(pair, qty)
                    print(f"{base_asset} BUY: {qty} @ {price}", flush=True)

            # =========================
            # SELL
            # =========================
            elif action == "sell":
                asset_balance = get_balance(base_asset)

                if asset_balance > 0:
                    kraken.create_market_sell_order(pair, asset_balance)
                    print(f"{base_asset} SELL: {asset_balance} @ {price}", flush=True)

        return jsonify({"status": "success"})

    except Exception as e:
        print(f"ERROR: {str(e)}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# =========================
# RUN (RENDER FIX)
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🚦 MODE: {MODE} | Using {ALLOCATION*100:.1f}% allocation", flush=True)
    app.run(host="0.0.0.0", port=port)