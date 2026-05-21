from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os
from datetime import datetime, time
import pytz
import time as pytime
import json

app = Flask(__name__)

# =========================================================
# ALPACA CONFIG
# =========================================================
api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://api.alpaca.markets"
)

# =========================================================
# SETTINGS
# =========================================================
DEFAULT_NOTIONAL = 3500
last_signal = {}

# =========================================================
# MARKET HOURS
# =========================================================
def is_regular_hours():
    eastern = pytz.timezone("US/Eastern")
    now = datetime.now(eastern).time()
    return time(9, 30) <= now <= time(16, 0)

# =========================================================
# POSITION HELPERS
# =========================================================
def get_position(symbol):
    try:
        pos = api.get_position(symbol)
        return float(pos.qty)
    except:
        return 0.0

def get_reliable_price(symbol, side="buy"):
    """Improved price fetching for premarket"""
    try:
        quote = api.get_latest_quote(symbol)
        ask = float(quote.ap) if quote.ap else 0
        bid = float(quote.bp) if quote.bp else 0
        
        print(f"QUOTE - Ask: {ask} | Bid: {bid}", flush=True)
        
        if side == "buy":
            if ask > 0:
                print(f"Using ASK: {ask}", flush=True)
                return ask
            elif bid > 0:
                print(f"Using BID fallback: {bid}", flush=True)
                return bid
        else:  # sell
            if bid > 0:
                return bid
            elif ask > 0:
                return ask
    except Exception as e:
        print(f"Quote error: {e}", flush=True)

    # Fallback to last trade
    try:
        trade = api.get_latest_trade(symbol)
        price = float(trade.price)
        print(f"Using LAST TRADE fallback: {price}", flush=True)
        return price
    except Exception as e:
        print(f"Trade fallback error: {e}", flush=True)
        return None

# =========================================================
# EXTENDED BUY LIMIT - TIGHTER FOR PREMARKET
# =========================================================
def get_extended_buy_limit(symbol):
    ref_price = get_reliable_price(symbol, "buy")
    if not ref_price or ref_price <= 0:
        print("Failed to get reliable price for buy limit", flush=True)
        return None

    # Tighter buffer = fewer rejections in premarket
    limit_price = round(ref_price * 1.012, 2)   # 1.2%
    print(f"FINAL BUY LIMIT (premarket): {limit_price} based on {ref_price}", flush=True)
    return limit_price

# =========================================================
# EXTENDED SELL LIMIT
# =========================================================
def get_extended_sell_limit(symbol):
    ref_price = get_reliable_price(symbol, "sell")
    if not ref_price or ref_price <= 0:
        return None
    limit_price = round(ref_price * 0.99, 2)
    print(f"FINAL SELL LIMIT: {limit_price} based on {ref_price}", flush=True)
    return limit_price

# =========================================================
# SELL HELPERS (unchanged except using new price func)
# =========================================================
def sell_qty(symbol, qty, is_extended=False):
    if qty <= 0:
        return
    try:
        if is_extended:
            limit_price = get_extended_sell_limit(symbol)
            if not limit_price:
                return
            order = api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="limit",
                time_in_force="day",
                limit_price=limit_price,
                extended_hours=True
            )
            print(f"LIMIT SELL {qty} {symbol} @ {limit_price}", flush=True)
        else:
            order = api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="market",
                time_in_force="day"
            )
            print(f"MARKET SELL {qty} {symbol}", flush=True)
        print(f"SELL ORDER ID: {order.id}", flush=True)
    except Exception as e:
        print(f"SELL ERROR: {e}", flush=True)

def close_position(symbol, is_extended=False):
    qty = get_position(symbol)
    if qty > 0:
        sell_qty(symbol, qty, is_extended)
    else:
        print(f"NO POSITION TO CLOSE FOR {symbol}", flush=True)

# =========================================================
# SIGNAL NORMALIZER (unchanged)
# =========================================================
def normalize_signal(raw):
    if not raw:
        return ""
    s = str(raw).upper().strip()
    print(f"RAW SIGNAL RECEIVED: '{raw}'", flush=True)
    s_clean = s.replace(" ", "").replace("-", "").replace("_", "").replace(".", "")
    print(f"CLEANED SIGNAL: '{s_clean}'", flush=True)

    if any(x in s_clean for x in ["EXITLONG", "CLOSELONG", "EXIT", "CLOSE", "SL", "BE", "BREAKEVEN"]):
        return "EXIT_LONG"
    if "TP1" in s_clean: return "TP1"
    if "TP2" in s_clean: return "TP2"
    if "TP3" in s_clean: return "TP3"
    if "TP4" in s_clean: return "TP4"
    if any(x in s_clean for x in ["LONG", "ENTRY", "OPENLONG"]):
        return "OPEN_LONG"
    return ""

# =========================================================
# DUPLICATE FILTER
# =========================================================
def already_fired(symbol, signal):
    key = f"{symbol}:{signal}"
    now = pytime.time()
    if key in last_signal and now - last_signal[key] < 2:
        return True
    last_signal[key] = now
    return False

# =========================================================
# WEBHOOK
# =========================================================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        print("================================================", flush=True)
        print("WEBHOOK RECEIVED", flush=True)

        raw_bytes = request.get_data(as_text=False)
        print(raw_bytes, flush=True)

        data = None
        try:
            data = request.get_json(force=True, silent=True)
        except:
            pass
        if not data and raw_bytes:
            try:
                data = json.loads(raw_bytes.decode("utf-8", errors="ignore"))
            except:
                pass

        print(f"PARSED DATA: {data}", flush=True)
        if not data:
            return jsonify({"status": "no_data"}), 200

        symbol = data.get("ticker") or data.get("symbol")
        raw_signal = data.get("signal")
        signal = normalize_signal(raw_signal)

        print(f"FINAL PARSED → {symbol} | '{raw_signal}' → {signal}", flush=True)

        if not symbol or not signal:
            return jsonify({"status": "bad_payload"}), 200

        if already_fired(symbol, signal):
            print("DUPLICATE BLOCKED", flush=True)
            return jsonify({"status": "duplicate"}), 200

        qty_pos = get_position(symbol)
        extended = not is_regular_hours()

        print(f"CURRENT POSITION {symbol}: {qty_pos}", flush=True)

        # ==================== OPEN LONG ====================
        if signal == "OPEN_LONG":
            if qty_pos > 0:
                return jsonify({"status": "already_in_position"}), 200

            try:
                notional = float(data.get("notional", DEFAULT_NOTIONAL))
            except:
                notional = DEFAULT_NOTIONAL

            print(f"NOTIONAL RECEIVED: {notional}", flush=True)

            last_price = get_reliable_price(symbol, "buy")
            if not last_price or last_price <= 0:
                return jsonify({"status": "price_fetch_fail"}), 200

            # === PRICE SANITY CHECK ===
            if not (300 < last_price < 1200):   # Safe range for MU-type stocks
                print(f"PRICE OUT OF BOUNDS ({last_price}) - ABORTING ORDER", flush=True)
                return jsonify({"status": "price_sanity_fail"}), 200

            qty = int(notional / last_price)
            if qty <= 0:
                return jsonify({"status": "qty_fail"}), 200

            print(f"QTY: {qty} | EST VALUE: {qty * last_price}", flush=True)

            if not extended:
                # Regular hours
                order = api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="buy",
                    type="market",
                    time_in_force="day"
                )
                print(f"MARKET BUY {qty} {symbol} | Order ID: {order.id}", flush=True)
            else:
                # Extended / Premarket
                limit_price = get_extended_buy_limit(symbol)
                if not limit_price:
                    return jsonify({"status": "bad_limit"}), 200

                order = api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="buy",
                    type="limit",
                    time_in_force="day",
                    limit_price=limit_price,
                    extended_hours=True
                )
                print(f"LIMIT BUY {qty} {symbol} @ {limit_price} | Order ID: {order.id}", flush=True)

            return jsonify({"status": "entry_sent"}), 200

        # ==================== EXIT LONG ====================
        if signal == "EXIT_LONG":
            print("EXIT SIGNAL RECEIVED", flush=True)
            close_position(symbol, extended)
            return jsonify({"status": "exit_sent"}), 200

        # Take Profit logic (kept your original)
        if qty_pos <= 0:
            return jsonify({"status": "no_position"}), 200

        qty = float(qty_pos)
        sold = 0
        if signal == "TP1": sold = int(qty * 0.20)
        elif signal == "TP2": sold = int(qty * 0.20)
        elif signal == "TP3": sold = int(qty * 0.20)
        elif signal == "TP4": sold = int(qty * 0.10)

        if sold > 0:
            sell_qty(symbol, sold, extended)
            print(f"{signal}: SOLD {sold} OF {int(qty)}", flush=True)

        return jsonify({"status": "processed"}), 200

    except Exception as e:
        print(f"WEBHOOK ERROR: {e}", flush=True)
        return jsonify({"status": "error"}), 200

# =========================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)
