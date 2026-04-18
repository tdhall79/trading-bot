from flask import Flask, request
import ccxt
import time

app = Flask(__name__)

api = ccxt.kraken({
    'apiKey': 'nloJM+TPJGCYdu5+KobDyFDAd+DPZGCuHv7+CI1wu9bsOpUilxssMuKB',
    'secret': 'vWzTX6FWytEDTn2t8wqHi1KIqb3JY/WkpEYzdbfOunzuS9wM8ALqOa9XlpPI4cnfav9iClQkTyI7i3fqJXNLsA==',
    'enableRateLimit': True
})

SYMBOL = "BTC/USD"

# === SETTINGS ===
RISK_PERCENT = 0.07
COOLDOWN = 15

# === TRACK POSITIONS PER STRATEGY ===
positions = {
    "breakout": False,
    "mean": False
}

last_trade_time = 0

def get_balances():
    balance = api.fetch_balance()
    usd = balance['total'].get('USD', 0)
    btc = balance['total'].get('BTC', 0)
    return usd, btc

def get_price():
    return api.fetch_ticker(SYMBOL)['last']

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

    if now - last_trade_time < COOLDOWN:
        print("⏱ cooldown", flush=True)
        return "cooldown"

    try:
        usd, btc = get_balances()
        price = get_price()

        qty = (usd * RISK_PERCENT) / price

        # === BUY ===
        if side == "buy":
            if positions[strategy]:
                print(f"{strategy} already in position", flush=True)
                return "already in"

            order = api.create_market_order(SYMBOL, "buy", qty)
            positions[strategy] = True
            last_trade_time = now

            print(f"✅ BUY {strategy}", flush=True)
            return "buy ok"

        # === SELL ===
        elif side == "sell":
            if not positions[strategy]:
                print(f"{strategy} no position", flush=True)
                return "no position"

            order = api.create_market_order(SYMBOL, "sell", btc)
            positions[strategy] = False
            last_trade_time = now

            print(f"✅ SELL {strategy}", flush=True)
            return "sell ok"

        return "invalid"

    except Exception as e:
        print("❌ ERROR:", e, flush=True)
        return str(e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)