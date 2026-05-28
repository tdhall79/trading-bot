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

# =========================================================
# EXTENDED HOURS AGGRESSION
# =========================================================

NORMAL_BUY_PREMIUM = 0.01
NORMAL_SELL_DISCOUNT = 0.01

CHEAP_STOCK_BUY_PREMIUM = 0.02
CHEAP_STOCK_SELL_DISCOUNT = 0.02

# Duplicate alert protection
last_signal = {}

# =========================================================
# HOME
# =========================================================

@app.route("/", methods=["GET"])
def home():

    return "ALIVE", 200

# =========================================================
# MARKET HOURS
# =========================================================

def is_regular_hours():

    eastern = pytz.timezone("US/Eastern")

    now = datetime.now(eastern).time()

    return time(9, 30) <= now <= time(16, 0)

# =========================================================
# POSITION HELPER
# =========================================================

def get_position(symbol):

    try:

        pos = api.get_position(symbol)

        qty = float(pos.qty)

        print(
            f"CURRENT POSITION {symbol}: {qty}",
            flush=True
        )

        return qty

    except:

        return 0

# =========================================================
# GET QUOTE
# =========================================================

def get_quote(symbol):

    try:

        quote = api.get_latest_quote(symbol)

        bid = float(quote.bid_price or 0)
        ask = float(quote.ask_price or 0)

        print(
            f"QUOTE {symbol} | BID: {bid} | ASK: {ask}",
            flush=True
        )

        return bid, ask

    except Exception as e:

        print(
            f"QUOTE ERROR: {e}",
            flush=True
        )

        return 0, 0

# =========================================================
# LAST TRADE PRICE
# =========================================================

def get_trade_price(symbol):

    try:

        trade = api.get_latest_trade(symbol)

        price = float(trade.price)

        print(
            f"LATEST TRADE PRICE: {price}",
            flush=True
        )

        return price

    except Exception as e:

        print(
            f"TRADE PRICE ERROR: {e}",
            flush=True
        )

        return 0

# =========================================================
# EXTENDED BUY LIMIT
# =========================================================

def get_extended_buy_limit(symbol):

    try:

        bid, ask = get_quote(symbol)

        if ask <= 0:

            ask = get_trade_price(symbol)

        if ask <= 0:

            return None

        premium = NORMAL_BUY_PREMIUM

        if ask < 20:
            premium = CHEAP_STOCK_BUY_PREMIUM

        limit_price = round(
            ask * (1 + premium),
            2
        )

        print(
            f"FINAL BUY LIMIT: {limit_price}",
            flush=True
        )

        return limit_price

    except Exception as e:

        print(
            f"BUY LIMIT ERROR: {e}",
            flush=True
        )

        return None

# =========================================================
# EXTENDED SELL LIMIT
# =========================================================

def get_extended_sell_limit(symbol):

    try:

        bid, ask = get_quote(symbol)

        if bid <= 0:

            bid = get_trade_price(symbol)

        if bid <= 0:

            return None

        discount = NORMAL_SELL_DISCOUNT

        if bid < 20:
            discount = CHEAP_STOCK_SELL_DISCOUNT

        limit_price = round(
            bid * (1 - discount),
            2
        )

        print(
            f"FINAL SELL LIMIT: {limit_price}",
            flush=True
        )

        return limit_price

    except Exception as e:

        print(
            f"SELL LIMIT ERROR: {e}",
            flush=True
        )

        return None

# =========================================================
# QTY CALC
# =========================================================

def calc_qty(notional, price):

    if price <= 0:

        return 0

    qty = int(notional / price)

    return qty

# =========================================================
# SIGNAL NORMALIZER
# =========================================================

def normalize_signal(raw):

    if not raw:

        return ""

    s = str(raw).upper().strip()

    print(
        f"RAW SIGNAL RECEIVED: '{raw}'",
        flush=True
    )

    s_clean = (
        s.replace(" ", "")
         .replace("-", "")
         .replace("_", "")
         .replace(".", "")
    )

    print(
        f"CLEANED SIGNAL: '{s_clean}'",
        flush=True
    )

    # =====================================================
    # EXITS
    # =====================================================

    if any(x in s_clean for x in [
        "EXITLONG",
        "CLOSELONG",
        "EXIT",
        "CLOSE",
        "SL",
        "BE",
        "BREAKEVEN"
    ]):
        return "EXIT_LONG"

    # =====================================================
    # TAKE PROFITS
    # =====================================================

    if "TP1" in s_clean:
        return "TP1"

    if "TP2" in s_clean:
        return "TP2"

    if "TP3" in s_clean:
        return "TP3"

    if "TP4" in s_clean:
        return "TP4"

    # =====================================================
    # ENTRIES
    # =====================================================

    if any(x in s_clean for x in [
        "LONG",
        "ENTRY",
        "OPENLONG"
    ]):
        return "OPEN_LONG"

    return ""

# =========================================================
# DUPLICATE FILTER
# =========================================================

def already_fired(symbol, signal):

    key = f"{symbol}:{signal}"

    now = pytime.time()

    if key in last_signal:

        elapsed = now - last_signal[key]

        if elapsed < 2:

            print(
                f"DUPLICATE BLOCKED ({elapsed:.2f}s)",
                flush=True
            )

            return True

    last_signal[key] = now

    return False

# =========================================================
# SELL HELPER
# =========================================================

def sell_qty(symbol, qty, extended=False):

    if qty <= 0:

        return

    try:

        # =================================================
        # EXTENDED HOURS SELL
        # =================================================

        if extended:

            limit_price = get_extended_sell_limit(symbol)

            if not limit_price:

                print(
                    "FAILED TO CREATE SELL LIMIT",
                    flush=True
                )

                return

            order = api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="limit",
                limit_price=limit_price,
                time_in_force="day",
                extended_hours=True
            )

            print(
                f"LIMIT SELL {qty} {symbol} @ {limit_price}",
                flush=True
            )

            print(
                f"SELL ORDER ID: {order.id}",
                flush=True
            )

        # =================================================
        # REGULAR HOURS SELL
        # =================================================

        else:

            order = api.submit_order(
                symbol=symbol,
                qty=qty,
                side="sell",
                type="market",
                time_in_force="day"
            )

            print(
                f"MARKET SELL {qty} {symbol}",
                flush=True
            )

            print(
                f"SELL ORDER ID: {order.id}",
                flush=True
            )

    except Exception as e:

        print(
            f"SELL ERROR: {e}",
            flush=True
        )

# =========================================================
# CLOSE POSITION
# =========================================================

def close_position(symbol, extended=False):

    qty = get_position(symbol)

    if qty <= 0:

        print(
            f"NO POSITION TO CLOSE FOR {symbol}",
            flush=True
        )

        return

    sell_qty(
        symbol,
        qty,
        extended
    )

# =========================================================
# WEBHOOK
# =========================================================

@app.route("/webhook", methods=["POST"])
def webhook():

    try:

        print(
            "================================================",
            flush=True
        )

        print(
            "WEBHOOK RECEIVED",
            flush=True
        )

        raw_bytes = request.get_data(as_text=False)

        print(
            raw_bytes,
            flush=True
        )

        data = None

        # =================================================
        # STANDARD JSON PARSE
        # =================================================

        try:

            data = request.get_json(
                force=True,
                silent=True
            )

        except:

            pass

        # =================================================
        # FALLBACK JSON PARSE
        # =================================================

        if not data and raw_bytes:

            try:

                data = json.loads(
                    raw_bytes.decode(
                        "utf-8",
                        errors="ignore"
                    )
                )

            except:

                pass

        print(
            f"PARSED DATA: {data}",
            flush=True
        )

        if not data:

            return jsonify({
                "status": "no_data"
            }), 200

        # =================================================
        # PARSE PAYLOAD
        # =================================================

        symbol = (
            data.get("ticker")
            or data.get("symbol")
        )

        raw_signal = data.get("signal")

        signal = normalize_signal(raw_signal)

        print(
            f"FINAL PARSED → {symbol} | '{raw_signal}' → {signal}",
            flush=True
        )

        if not symbol or not signal:

            return jsonify({
                "status": "bad_payload"
            }), 200

        # =================================================
        # DUPLICATE FILTER
        # =================================================

        if already_fired(symbol, signal):

            return jsonify({
                "status": "duplicate"
            }), 200

        # =================================================
        # SESSION
        # =================================================

        extended = not is_regular_hours()

        print(
            f"EXTENDED HOURS: {extended}",
            flush=True
        )

        qty_pos = get_position(symbol)

        # =================================================
        # OPEN LONG
        # =================================================

        if signal == "OPEN_LONG":

            if qty_pos > 0:

                return jsonify({
                    "status": "already_in_position"
                }), 200

            try:

                notional = float(
                    data.get(
                        "notional",
                        DEFAULT_NOTIONAL
                    )
                )

            except:

                notional = DEFAULT_NOTIONAL

            print(
                f"NOTIONAL: {notional}",
                flush=True
            )

            # =============================================
            # USE ASK PRICE FOR ACCURATE PREMARKET SIZING
            # =============================================

            bid, ask = get_quote(symbol)

            reference_price = ask

            if reference_price <= 0:

                reference_price = get_trade_price(symbol)

            if reference_price <= 0:

                return jsonify({
                    "status": "bad_price"
                }), 200

            qty = calc_qty(
                notional,
                reference_price
            )

            print(
                f"QTY: {qty}",
                flush=True
            )

            print(
                f"EST VALUE: {qty * reference_price}",
                flush=True
            )

            if qty <= 0:

                return jsonify({
                    "status": "qty_fail"
                }), 200

            # =============================================
            # REGULAR HOURS BUY
            # =============================================

            if not extended:

                try:

                    order = api.submit_order(
                        symbol=symbol,
                        qty=qty,
                        side="buy",
                        type="market",
                        time_in_force="day"
                    )

                    print(
                        f"MARKET BUY {qty} {symbol}",
                        flush=True
                    )

                    print(
                        f"BUY ORDER ID: {order.id}",
                        flush=True
                    )

                except Exception as e:

                    print(
                        f"BUY ORDER ERROR: {e}",
                        flush=True
                    )

            # =============================================
            # EXTENDED HOURS BUY
            # =============================================

            else:

                limit_price = get_extended_buy_limit(symbol)

                if not limit_price:

                    return jsonify({
                        "status": "bad_limit"
                    }), 200

                try:

                    order = api.submit_order(
                        symbol=symbol,
                        qty=qty,
                        side="buy",
                        type="limit",
                        limit_price=limit_price,
                        time_in_force="day",
                        extended_hours=True
                    )

                    print(
                        f"LIMIT BUY {qty} {symbol} @ {limit_price}",
                        flush=True
                    )

                    print(
                        f"BUY ORDER ID: {order.id}",
                        flush=True
                    )

                except Exception as e:

                    print(
                        f"BUY ORDER ERROR: {e}",
                        flush=True
                    )

            return jsonify({
                "status": "entry_sent"
            }), 200

        # =================================================
        # EXIT LONG
        # =================================================

        if signal == "EXIT_LONG":

            print(
                "EXIT SIGNAL RECEIVED",
                flush=True
            )

            close_position(
                symbol,
                extended
            )

            return jsonify({
                "status": "exit_sent"
            }), 200

        # =================================================
        # TP WITHOUT POSITION
        # =================================================

        if qty_pos <= 0:

            return jsonify({
                "status": "no_position"
            }), 200

        # =================================================
        # TAKE PROFITS
        # =================================================

        qty = float(qty_pos)

        sold = 0

        if signal == "TP1":
            sold = int(qty * 1.0)

        elif signal == "TP2":
            sold = int(qty * 1.0)

        elif signal == "TP3":
            sold = int(qty * 1.0)

        elif signal == "TP4":
            sold = int(qty * 1.0)

        if sold > 0:

            sell_qty(
                symbol,
                sold,
                extended
            )

            print(
                f"{signal}: SOLD {sold} OF {int(qty)}",
                flush=True
            )

        return jsonify({
            "status": "processed"
        }), 200

    except Exception as e:

        print(
            f"WEBHOOK ERROR: {e}",
            flush=True
        )

        return jsonify({
            "status": "error"
        }), 200

# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
