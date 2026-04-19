from flask import Flask, request
import ccxt
import time

app = Flask(__name__)

# === KRAKEN SETUP ===
api = ccxt.kraken({
    'apiKey': 'bHdCNRhjstY9Pi47ZkzbJpcVGJShaG4lJAX7P/mXhBMXP86oCQTpzxHT',
    'secret': 'a1QozQ48u4Ks4baZgvAWOBHvQjWc+j6tbbyY3v4K3MKY572qaaE+CrjV7nbXs5E4I7wKWAjedMNQDPqY1ZelHg==',
    'enableRateLimit': True
})

SYMBOL = "SOL/USD"

# === SETTINGS ===
ALLOCATION = 0.85   # 85% of account per trade
COOLDOWN = 10       # seconds between trades
MIN_QTY = 0.01      # minimum SOL size

# === STATE TRACKING ===
in_position = False
last_trade_time = 0

# === HELPERS ===
def get_balance():
    for i in range(3):
        try:
            balance = api.fetch_balance()
            usd = balance['total'].get('USD', 0)
            sol = balance['total'].get('SOL', 0)
            return usd, sol
        except Exception as e:
            print(f"❌ Balance error {i+1}: {e}", flush=True)
            time.sleep(2)
    return 0, 0

def get_price():
    return api.fetch_ticker(SYMBOL)['last']

# === WEBHOOK ===
@app.route('/webhook', methods=['POST'])
def webhook():
    global in_position, last_trade_time

    data = request.json
    print("🔥 RECEIVED:", data, flush=True)

    side = data.get("action")

    now = time.time()

    # === COOLDOWN ===
    if now - last_trade_time < COOLDOWN:
        print("⏱ Cooldown active", flush=True)
        return "Cooldown"

    try:
        usd, sol = get_balance()
        price = get_price()

        print(f"USD: {usd}, SOL: {sol}, Price: {price}", flush=True)

        # ======================
        # BUY
        # ======================
        if side == "buy":
            if in_position:
                print("⚠️ Already in position", flush=True)
                return "Already in position"

            usd_to_use = usd * ALLOCATION
            amount = usd_to_use / price
            amount = round(amount, 4)

            if amount < MIN_QTY:
                print(f"⚠️ Order too small: {amount}", flush=True)
                return "Too small"

            order = api.create_market_order(SYMBOL, "buy", amount)

            in_position = True
            last_trade_time = now

            print(f"✅ BUY: {amount} SOL (~${usd_to_use})", flush=True)
            return "Buy executed"

        # ======================
        # SELL
        # ======================
        elif side == "sell":
            if not in_position:
                print("⚠️ No position", flush=True)
                return "No position"

            # Retry logic (VERY IMPORTANT)
            for attempt in range(5):
                try:
                    usd, sol = get_balance()

                    print(f"Sell attempt {attempt+1} | SOL: {sol}", flush=True)

                    if sol <= 0:
                        print("⚠️ No SOL yet, retrying...", flush=True)
                        time.sleep(2)
                        continue

                    sol = round(sol, 4)

                    order = api.create_market_order(SYMBOL, "sell", sol)

                    in_position = False
                    last_trade_time = now

                    print(f"✅ SELL: {sol} SOL", flush=True)
                    return "Sell executed"

                except Exception as e:
                    print(f"❌ SELL ERROR {attempt+1}: {e}", flush=True)
                    time.sleep(2)

            return "Sell failed"

        return "Invalid action"

    except Exception as e:
        print("❌ ERROR FULL:", repr(e), flush=True)
        return str(e)

# === RUN SERVER ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)