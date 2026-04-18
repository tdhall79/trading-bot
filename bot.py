from flask import Flask, request
import ccxt
import time

app = Flask(__name__)

# === KRAKEN KEYS ===
api = ccxt.kraken({
    'apiKey': 'YOUR_API_KEY',
    'secret': 'YOUR_SECRET_KEY',
    'enableRateLimit': True
})

SYMBOL = "BTC/USD"

# === STATE TRACKING ===
last_action = None
last_trade_time = 0
cooldown_seconds = 30  # prevents rapid repeat trades

# === GET BTC BALANCE ===
def get_btc_balance():
    balance = api.fetch_balance()
    return balance['total'].get('BTC', 0)

@app.route('/webhook', methods=['POST'])
def webhook():
    global last_action, last_trade_time

    data = request.json
    print("🔥 WEBHOOK RECEIVED:", data, flush=True)

    side = data.get("action")
    qty = float(data.get("quantity"))

    now = time.time()

    try:
        btc_balance = get_btc_balance()
        print(f"Current BTC balance: {btc_balance}", flush=True)

        # ======================
        # COOLDOWN PROTECTION
        # ======================
        if now - last_trade_time < cooldown_seconds:
            print("⏱ Cooldown active — skipping", flush=True)
            return "Cooldown active"

        # ======================
        # BUY LOGIC
        # ======================
        if side == "buy":
            if btc_balance > 0:
                print("⚠️ Already holding BTC — skip", flush=True)
                return "Already holding"

            if last_action == "buy":
                print("⚠️ Last action was buy — skip duplicate", flush=True)
                return "Duplicate buy blocked"

            try:
                order = api.create_market_order(SYMBOL, "buy", qty)
                print("✅ BUY ORDER PLACED:", order, flush=True)
                last_action = "buy"
                last_trade_time = now
                return "buy executed"

            except Exception as e:
                print("❌ BUY FAILED:", e, flush=True)
                last_action = "buy"  # still block spam
                last_trade_time = now
                return str(e)

        # ======================
        # SELL LOGIC
        # ======================
        elif side == "sell":
            if btc_balance <= 0:
                print("⚠️ No BTC to sell — skip", flush=True)
                return "No BTC"

            if last_action == "sell":
                print("⚠️ Last action was sell — skip duplicate", flush=True)
                return "Duplicate sell blocked"

            try:
                order = api.create_market_order(SYMBOL, "sell", qty)
                print("✅ SELL ORDER PLACED:", order, flush=True)
                last_action = "sell"
                last_trade_time = now
                return "sell executed"

            except Exception as e:
                print("❌ SELL FAILED:", e, flush=True)
                last_action = "sell"
                last_trade_time = now
                return str(e)

        else:
            return "Invalid action"

    except Exception as e:
        print("❌ ERROR:", e, flush=True)
        return str(e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)