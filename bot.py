from flask import Flask, request
import ccxt

app = Flask(__name__)

# === KRAKEN KEYS ===
api = ccxt.kraken({
    'apiKey': 'nloJM+TPJGCYdu5+KobDyFDAd+DPZGCuHv7+CI1wu9bsOpUilxssMuKB',
    'secret': 'vWzTX6FWytEDTn2t8wqHi1KIqb3JY/WkpEYzdbfOunzuS9wM8ALqOa9XlpPI4cnfav9iClQkTyI7i3fqJXNLsA=='
    'enableRateLimit': True,
})

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("Received:", data)

    symbol = "BTC/USD"
    side = data.get("action")
    qty = float(data.get("quantity"))

    try:
        order = api.create_market_order(symbol, side, qty)
        print(order)
        return "order placed"

    except Exception as e:
        print("ERROR:", e)
        return str(e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
