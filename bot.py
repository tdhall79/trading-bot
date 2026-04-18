from flask import Flask, request
import ccxt

app = Flask(__name__)

# === KRAKEN KEYS ===
api = ccxt.kraken({
    'apiKey': 'PASTE_YOUR_API_KEY_HERE',
    'secret': 'PASTE_YOUR_SECRET_KEY_HERE',
    'enableRateLimit': True
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
   
