from flask import Flask, request
import ccxt
import time

app = Flask(__name__)

# === KRAKEN SETUP ===
api = ccxt.kraken({
    'apiKey': 'nloJM+TPJGCYdu5+KobDyFDAd+DPZGCuHv7+CI1wu9bsOpUilxssMuKB',
    'secret': 'vWzTX6FWytEDTn2t8wqHi1KIqb3JY/WkpEYzdbfOunzuS9wM8ALqOa9XlpPI4cnfav9iClQkTyI7i3fqJXNLsA==',
    'enableRateLimit': True
})

SYMBOL = "BTC/USD"

# === SETTINGS ===
RISK_PERCENT = 0.07
COOLDOWN = 15
MIN_QTY = 0.00001

# === STATE TRACKING ===
positions = {
    "breakout": False,
    "mean": False
}

last_trade_time = 0

# === HELPERS ===
def get_balances():
    balance = api.fetch_balance()
    usd = balance['total'].get('USD', 0)
    btc = balance['total'].get('BTC', 0)
    return usd, btc

def get_price():
    return api.fetch_ticker(SYMBOL)['last']

def calculate_qty(usd, price):
    raw_qty = (usd * RISK_PERCENT) / price
    qty = round(raw_qty, 8)
    return qty

# === WEBHOOK ===
@app.route('/webhook', methods=['POST'])
def webhook():
    global last_trade_time

    data = request.json
    print("🔥 RECEIVED:", data, flush=True)

    side = data.get("action")
    strategy = data.get("strategy")

    if strategy not in positions:
        return "Invalid strategy"

    now = time.time()

    # === COOLDOWN ===
    if now - last_trade_time < COOLDOWN:
        print("⏱ Cooldown active", flush=True)
        return "Cooldown"

    try:
        usd, btc = get_balances()
        price = get_price()

        print(f"USD: {usd}, BTC: {btc}, Price: {price}", flush=True)

        qty = calculate_qty(usd, price)

        # === MIN SIZE CHECK ===
        if qty < MIN_QTY:
            print(f"⚠️ Order too small: {qty}", flush=True)
            return "Order too small"

        # ======================
        # BUY
        # ======================
        if side == "buy":
            if positions[strategy]:
                print(f"⚠️ {strategy} already in position", flush=True)
                return "Already in position"

            order = api.create_market_order(SYMBOL, "buy", qty)
            positions[strategy] = True
            last_trade_time = now

            print(f"✅ BUY {strategy}: {qty}", flush=True)
            return "Buy executed"

        # ======================
        # SELL
        # ======================
        elif side == "sell":
            if not positions[strategy]:
                print(f"⚠️ {strategy} no position", flush=True)
                return "No position"

            order = api.create_market_order(SYMBOL, "sell", btc)
            positions[strategy] = False
            last_trade_time = now

            print(f"✅ SELL {strategy}: {btc}", flush=True)
            return "Sell executed"

        return "Invalid action"

    except Exception as e:
        print("❌ ERROR:", e, flush=True)
        return str(e)

# === RUN SERVER ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)