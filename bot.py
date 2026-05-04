from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os
from datetime import datetime, time
import pytz

app = Flask(__name__)

api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://api.alpaca.markets"
)

# =========================
# CONFIG
# =========================
DEFAULT_NOTIONAL = 7000
EXTENDED_LIMIT_OFFSET = 0.005

# =========================
# SESSION CHECK (ENTRY ONLY)
# =========================
def is_regular_hours():
    eastern = pytz.timezone("US/Eastern")
    now = datetime.now(eastern).time()
    return time(9, 30) <= now <= time(16, 0)

# =========================
# POSITION
# =========================
def get_position(symbol):
    try:
        return api.get_position(symbol)
    except:
        return None

# =========================
# PRICE
# =========================
def get_quote(symbol):
    q = api.get_latest_quote(symbol)
    return float(q.ap), float(q.bp)

# =========================
# SIZE CALC
# =========================
def calc_qty(notional, price):
    if price <= 0:
        return 0
    return int(notional / price)

# =========================
# WEBHOOK
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)

        print("WEBHOOK:", data, flush=True)

        symbol = data.get("symbol")
        signal = (data.get("signal") or "").upper()

        if not symbol or not signal:
            return jsonify({"error": "invalid payload"}), 400

        ask, bid = get_quote(symbol)
        position = get_position(symbol)
        is_long = position is not None

        regular = is_regular_hours()

        # =====================
        # OPEN LONG (SESSION-AWARE)
        # =====================
        if signal == "LONG":

            if is_long:
                return jsonify({"status": "already_in_position"}), 200

            notional = float(data.get("notional", DEFAULT_NOTIONAL))
            entry_price = ask

            qty = calc_qty(notional, entry_price)

            if qty <= 0:
                return jsonify({"error": "qty_calculation_failed"}), 400

            # REGULAR HOURS → MARKET
            if regular:
                api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="buy",
                    type="market",
                    time_in_force="day"
                )

                return jsonify({
                    "status": "long_market",
                    "qty": qty,
                    "notional": notional
                })

            # EXTENDED HOURS → AGGRESSIVE LIMIT
            limit_price = round(ask * (1 + EXTENDED_LIMIT_OFFSET), 2)

            api.submit_order(
                symbol=symbol,
                qty=qty,
                side="buy",
                type="limit",
                time_in_force="day",
                limit_price=limit_price,
                extended_hours=True
            )

            return jsonify({
                "status": "long_limit_extended",
                "qty": qty,
                "limit_price": limit_price,
                "notional": notional
            })

        # =====================
        # EXIT LONG (ALWAYS EXECUTES - NO FILTERS)
        # =====================
        if signal == "EXIT LONG":

            if not is_long:
                return jsonify({"status": "no_position"}), 200

            qty = float(position.qty)

            # ALWAYS MARKET OR LIQUIDITY-ADJUSTED LIMIT
            # (we still choose smart execution, but never block)

            if regular:
                api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="sell",
                    type="market",
                    time_in_force="day"
                )

                return jsonify({
                    "status": "exit_market_executed",
                    "qty_closed": qty
                })

            # extended hours exit
            limit_price = round(bid * (1 - EXTENDED_LIMIT_OFFSET), 2)

            api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="limit",
                time_in_force="day",
                limit_price=limit_price,
                extended_hours=True
            )

            return jsonify({
                "status": "exit_limit_extended",
                "qty_closed": qty,
                "limit_price": limit_price
            })

        return jsonify({"error": "unknown signal"}), 400

    except Exception as e:
        print("ERROR:", str(e), flush=True)
        return jsonify({"error": str(e)}), 500