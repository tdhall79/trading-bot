from flask import Flask, request
import ccxt
import time

app = Flask(__name__)

# === KRAKEN KEYS ===
api = ccxt.kraken({
    'apiKey': 'nloJM+TPJGCYdu5+KobDyFDAd+DPZGCuHv7+CI1wu9bsOpUilxssMuKB',
    'secret': 'vWzTX6FWytEDTn2t8wqHi1KIqb3JY/WkpEYzdbfOunzuS9wM8ALqOa9XlpPI4cnfav9iClQkTyI7i3fqJXNLsA==',
    'enableRateLimit': True
})

SYMBOL = "BTC/USD"

# === SETTINGS ===
RISK_PERCENT = 0.07          # 7% per trade
MAX_DRAWDOWN = 0.20          # 20% max drawdown stop
COOLDOWN = 30                # seconds between trades

# === STATE ===
starting_equity = None
last_trade_time = 0
last_action = None

# === GET BALANCE ===
def get_balances():
    balance = api.fetch_balance()
    usd = balance['total'].get('USD', 0)
    btc = balance['total'].get('BTC', 0)
    return usd, btc

# === CALCULATE POSITION SIZE ===
def calculate_position_size(usd_balance, price):
    usd_to_use = usd_balance * RISK_PERCENT
    qty = usd_to_use / price
    return qty

@app.route('/webhook', methods=['POST'])
def webhook():
    global starting_equity, last_trade_time, last_action

    data = request.json
    print("🔥 WEBHOOK RECEIVED:", data, flush=True)

    side = data.get("action")
    now = time.time()

    try:
        usd_balance, btc_balance = get_balances()
        ticker = api.fetch_ticker(SYMBOL)
        price = ticker['last']

        equity = usd_balance + (btc_balance * price)

        if starting_equity is None:
            starting_equity = equity

        drawdown = (starting_equity - equity) / starting_equity

        print(f"Equity: {equity}, Drawdown: {drawdown}", flush=True)

        # === DRAWDOWN PROTECTION ===
        if drawdown >= MAX_DRAWDOWN:
            print("🚨 Max drawdown hit — trading stopped", flush=True)
            return "Drawdown limit reached"

        # === COOLDOWN ===
        if now - last_trade_time < COOLDOWN:
            print("⏱ Cooldown active", flush=True)
            return "Cooldown"

        qty = calculate_position_size(usd_balance, price)

        # === BUY ===
        if side == "buy":
            if btc_balance > 0:
                print("⚠️ Already in position", flush=True)
                return "Already holding"

            order = api.create_market_order(SYMBOL, "buy", qty)
            print("✅ BUY:", order, flush=True)

            last_action = "buy"
            last_trade_time = now
            return "buy executed"

        # === SELL ===
        elif side == "sell":
            if btc_balance <= 0:
                print("⚠️ No BTC to sell", flush=True)
                return "No BTC"

            order = api.create_market_order(SYMBOL, "sell", btc_balance)
            print("✅ SELL:", order, flush=True)

            last_action = "sell"
            last_trade_time = now
            return "sell executed"

        else:
            return "Invalid action"

    except Exception as e:
        print("❌ ERROR:", e, flush=True)
        return str(e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)