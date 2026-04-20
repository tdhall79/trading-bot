from flask import Flask, request, jsonify
import os
import ccxt
import alpaca_trade_api as tradeapi

app = Flask(__name__)

# =========================
# CONFIG
# =========================
MODE = "LIVE"  # or "PAPER"

# % of account per trade (adjust if needed)
ALLOCATION = 0.10  # 10%

# =========================
# KRAKEN SETUP (BTC)
# =========================
kraken = ccxt.kraken({
    "apiKey": os.environ.get("KRAKEN_API_KEY"),
    "secret": os.environ.get("KRAKEN_SECRET"),
    "enableRateLimit": True
})

KRAKEN_SYMBOL = "BTC/USD"

# =========================
# ALPACA SETUP (STOCKS)
# =========================
alpaca = tradeapi.REST(
    os.environ.get("ALPACA_API_KEY"),
    os.environ.get("ALPACA_SECRET"),
    base_url="https://api.alpaca.markets" if MODE == "LIVE" else "https://paper-api.alpaca.markets"
)

# =========================
# HELPERS
# =========================
def get_kraken_balance():
    balance = kraken.fetch_balance()
    return balance["total"]["USD"]

def get_alpaca_equity():
    account = alpaca.get_account()
    return float(account.equity)

def get_alpaca_position_qty(symbol):
    try:
        pos = alpaca.get_position(symbol)
        return float(pos.qty)
    except:
        return 0.0

# =========================
# ROUTES
# =========================
@app.route("/", methods=["GET"])
def home():
    return "Bot is live"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print(f"Incoming: {data}", flush=True)

    action = data.get("action")   # "buy" or "sell"
    symbol = data.get("symbol")   # "BTCUSD", "NVDA", etc.
    price = float(data.get("price", 0))

    try:
        # =========================
        # BTC → KRAKEN
        # =========================
        if symbol == "BTCUSD":
            usd_balance = get_kraken_balance()
            allocation_value = usd_balance * ALLOCATION

            if action == "buy":
                qty = allocation_value / price
                qty = float(f"{qty:.8f}")  # Kraken precision

                order = kraken.create_market_buy_order(KRAKEN_SYMBOL, qty)
                print(f"BTC BUY: {qty}", flush=True)

            elif action == "sell":
                btc_balance = kraken.fetch_balance()["total"]["BTC"]

                if btc_balance > 0:
                    order = kraken.create_market_sell_order(KRAKEN_SYMBOL, btc_balance)
                    print(f"BTC SELL: {btc_balance}", flush=True)

        # =========================
        # STOCKS → ALPACA
        # =========================
        else:
            equity = get_alpaca_equity()
            allocation_value = equity * ALLOCATION

            if action == "buy":
                qty = int(allocation_value / price)

                if qty > 0:
                    alpaca.submit_order(
                        symbol=symbol,
                        qty=qty,
                        side="buy",
                        type="market",
                        time_in_force="day"
                    )
                    print(f"{symbol} BUY: {qty}", flush=True)

            elif action == "sell":
                qty = get_alpaca_position_qty(symbol)

                if qty > 0:
                    alpaca.submit_order(
                        symbol=symbol,
                        qty=qty,
                        side="sell",
                        type="market",
                        time_in_force="day"
                    )
                    print(f"{symbol} SELL: {qty}", flush=True)

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
