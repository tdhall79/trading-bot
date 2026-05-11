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

DEFAULT_NOTIONAL = 7000
EXTENDED_LIMIT_OFFSET = 0.02
TRAILING_STOP_PERCENT = 0.5

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
# POSITION HELPERS
# =========================================================

def get_position(symbol):

    try:

        pos = api.get_position(symbol)

        return float(pos.qty)

    except:

        return 0

def get_quote(symbol):

    try:

        q = api.get_latest_quote(symbol)

        ask = float(q.ap) if q.ap else 0
        bid = float(q.bp) if q.bp else 0

        # FALLBACK TO TRADE PRICE
        if ask <= 0:

            t = api.get_latest_trade(symbol)

            ask = float(t.price)

            print(f"USING TRADE PRICE FALLBACK FOR {symbol}: {ask}", flush=True)

        return ask, bid

    except Exception as e:

        print(f"QUOTE ERROR: {e}", flush=True)

        try:

            t = api.get_latest_trade(symbol)

            ask = float(t.price)

            print(f"USING TRADE FALLBACK FOR {symbol}: {ask}", flush=True)

            return ask, ask

        except Exception as e2:

            print(f"TRADE FALLBACK FAILED: {e2}", flush=True)

            return 0, 0

def calc_qty(notional, price):

    if price <= 0:
        return 0

    return int(notional / price)

# =========================================================
# TRAILING STOP
# =========================================================

def place_trailing_stop(symbol):

    qty = get_position(symbol)

    if qty <= 0:
        return

    try:

        api.submit_order(
            symbol=symbol,
            qty=qty,
            side="sell",
            type="trailing_stop",
            time_in_force="day",
            trail_percent=TRAILING_STOP_PERCENT
        )

        print(
            f"✅ TRAILING STOP {TRAILING_STOP_PERCENT}% placed for {symbol}",
            flush=True
        )

    except Exception as e:

        print(f"TRAILING STOP ERROR: {e}", flush=True)

# =========================================================
# SELL HELPERS
# =========================================================

def sell_qty(symbol, qty, is_extended=False):

    if qty <= 0:
        return

    try:

        if is_extended:

            _, bid = get_quote(symbol)

            limit_price = round(
                bid * (1 - 0.008),
                2
            ) if bid > 0 else None

            if limit_price:

                api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="sell",
                    type="limit",
                    time_in_force="day",
                    limit_price=limit_price,
                    extended_hours=True
                )

                print(
                    f"LIMIT SELL {qty} {symbol} @ {limit_price}",
                    flush=True
                )

            else:

                api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="sell",
                    type="market",
                    time_in_force="day"
                )

                print(
                    f"MARKET SELL FALLBACK {qty} {symbol}",
                    flush=True
                )

        else:

            api.submit_order(
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

    except Exception as e:

        print(f"SELL ERROR: {e}", flush=True)

def close_position(symbol, is_extended=False):

    qty = get_position(symbol)

    if qty > 0:

        sell_qty(symbol, qty, is_extended)

    else:

        print(f"NO POSITION TO CLOSE FOR {symbol}", flush=True)

# =========================================================
# SIGNAL NORMALIZER
# =========================================================

def normalize_signal(raw):

    if not raw:
        return ""

    s = str(raw).upper().strip()

    print(f"RAW SIGNAL RECEIVED: '{raw}'", flush=True)

    s_clean = (
        s.replace(" ", "")
         .replace("-", "")
         .replace("_", "")
         .replace(".", "")
    )

    print(f"CLEANED SIGNAL: '{s_clean}'", flush=True)

    # =====================================================
    # EXITS
    # =====================================================

    if any(x in s_clean for x in [
        "EXITLONG",
        "CLOSELONG",
        "EXIT",
        "CLOSE"
    ]):
        return "EXIT_LONG"

    if any(x in s_clean for x in [
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

    if key in last_signal and now - last_signal[key] < 2.0:
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

        # =================================================
        # NORMAL JSON PARSE
        # =================================================

        try:

            data = request.get_json(force=True, silent=True)

        except:

            pass

        # =================================================
        # MANUAL JSON PARSE
        # =================================================

        if not data and raw_bytes:

            try:

                data = json.loads(
                    raw_bytes.decode("utf-8", errors="ignore")
                )

            except:

                pass

        print(f"PARSED DATA: {data}", flush=True)

        # =================================================
        # RAW TEXT FALLBACK
        # =================================================

        if not data:

            raw_text = raw_bytes.decode(
                "utf-8",
                errors="ignore"
            ).strip()

            print("===== RAW TEXT FALLBACK =====", flush=True)
            print(f"RAW TEXT: '{raw_text}'", flush=True)

            return jsonify({
                "status": "no_data"
            }), 200

        # =================================================
        # NORMAL SIGNAL FLOW
        # =================================================

        symbol = data.get("ticker") or data.get("symbol")
        raw_signal = data.get("signal")

        # =================================================
        # FIXED NOTIONAL HANDLING
        # =================================================

        try:

            notional = float(
                data.get("notional", DEFAULT_NOTIONAL)
            )

        except:

            notional = DEFAULT_NOTIONAL

        signal = normalize_signal(raw_signal)

        print(
            f"FINAL PARSED → {symbol} | '{raw_signal}' → {signal}",
            flush=True
        )

        print(f"NOTIONAL RECEIVED: {notional}", flush=True)

        if not symbol or not signal:

            print("BAD PAYLOAD", flush=True)

            return jsonify({
                "status": "bad_payload"
            }), 200

        if already_fired(symbol, signal):

            print("DUPLICATE SIGNAL BLOCKED", flush=True)

            return jsonify({
                "status": "duplicate"
            }), 200

        qty_pos = get_position(symbol)

        extended = not is_regular_hours()

        print(
            f"CURRENT POSITION {symbol}: {qty_pos}",
            flush=True
        )

        # =================================================
        # OPEN LONG
        # =================================================

        if signal == "OPEN_LONG":

            if qty_pos > 0:

                print("ALREADY IN POSITION", flush=True)

                return jsonify({
                    "status": "already_in_position"
                }), 200

            ask, _ = get_quote(symbol)

            qty = calc_qty(notional, ask)

            print(f"ASK: {ask}", flush=True)
            print(f"QTY: {qty}", flush=True)
            print(f"EST VALUE: {qty * ask}", flush=True)

            if qty <= 0:

                print("QTY FAIL", flush=True)

                return jsonify({
                    "status": "qty_fail"
                }), 200

            # =============================================
            # REGULAR HOURS BUY
            # =============================================

            if not extended:

                api.submit_order(
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

            # =============================================
            # EXTENDED HOURS BUY
            # =============================================

            else:

                limit_price = round(
                    ask * (1 + EXTENDED_LIMIT_OFFSET),
                    2
                )

                api.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side="buy",
                    type="limit",
                    time_in_force="day",
                    limit_price=limit_price,
                    extended_hours=True
                )

                print(
                    f"LIMIT BUY {qty} {symbol} @ {limit_price}",
                    flush=True
                )

            return jsonify({
                "status": "entry_sent"
            }), 200

        # =================================================
        # EXIT LONG
        # =================================================

        if signal == "EXIT_LONG":

            print("EXIT SIGNAL RECEIVED", flush=True)

            close_position(symbol, extended)

            return jsonify({
                "status": "exit_sent"
            }), 200

        # =================================================
        # TP WITHOUT POSITION
        # =================================================

        if qty_pos <= 0:

            print(
                f"TP IGNORED - NO POSITION IN {symbol}",
                flush=True
            )

            return jsonify({
                "status": "no_position"
            }), 200

        # =================================================
        # TAKE PROFITS
        # =================================================

        qty = float(qty_pos)

        sold = 0

        if signal == "TP1":
            sold = int(qty * 0.25)

        elif signal == "TP2":
            sold = int(qty * 0.20)

        elif signal == "TP3":
            sold = int(qty * 0.10)

        elif signal == "TP4":
            sold = int(qty * 0.10)

        if sold > 0:

            sell_qty(symbol, sold, extended)

            print(
                f"{signal}: SOLD {sold} OF {int(qty)}",
                flush=True
            )

        return jsonify({
            "status": "processed"
        }), 200

    except Exception as e:

        print(f"WEBHOOK ERROR: {e}", flush=True)

        return jsonify({
            "status": "error"
        }), 200

# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
    )
