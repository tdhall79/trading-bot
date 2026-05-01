# =========================
# CONFIG (NEW)
# =========================
COOLDOWN = 30            # seconds between trades per symbol
MIN_SIGNAL_GAP = 2       # seconds required between opposite signals
USE_MARKET_ORDERS = True  # set False after testing

# =========================
# WEBHOOK
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        print("WEBHOOK:", data, flush=True)

        # =========================
        # CLEAN INPUT (CRITICAL)
        # =========================
        symbol = data.get("symbol", "").strip().upper()
        signal = (data.get("signal") or "").strip().upper()
        qty = float(data.get("qty", 0))
        offset = float(data.get("limit_offset", 0.01))
        event_time = int(data.get("time", 0))

        if not symbol or signal not in ["LONG", "EXIT LONG"]:
            return jsonify({"error": "invalid signal"}), 400

        if qty <= 0:
            return jsonify({"error": "invalid qty"}), 400

        if not event_time:
            return jsonify({"error": "missing time"}), 400

        # =========================
        # STATE INIT
        # =========================
        if symbol not in STATE:
            STATE[symbol] = {
                "last_event_time": 0,
                "last_event_id": None,
                "last_signal": None,
                "last_trade_time": 0
            }

        state = STATE[symbol]

        # =========================
        # STALE FILTER
        # =========================
        if is_stale(event_time):
            return jsonify({"status": "stale_ignored"}), 200

        # =========================
        # ORDERING
        # =========================
        if event_time < state["last_event_time"]:
            return jsonify({"status": "out_of_order_ignored"}), 200

        # =========================
        # DEDUP
        # =========================
        event_id = make_event_id(data)
        if event_id == state["last_event_id"]:
            return jsonify({"status": "duplicate_ignored"}), 200

        # =========================
        # CONFLICT FILTER (KEY FIX)
        # =========================
        time_diff = (event_time - state["last_event_time"]) / 1000

        if (
            state["last_signal"] is not None and
            signal != state["last_signal"] and
            time_diff < MIN_SIGNAL_GAP
        ):
            print(f"IGNORED FLIP: {state['last_signal']} -> {signal}", flush=True)
            return jsonify({"status": "flip_ignored"}), 200

        # =========================
        # COOLDOWN (ANTI-CHURN)
        # =========================
        if now() - state["last_trade_time"] < COOLDOWN:
            return jsonify({"status": "cooldown_active"}), 200

        # Update state AFTER filters
        state["last_event_time"] = event_time
        state["last_event_id"] = event_id
        state["last_signal"] = signal

        # =========================
        # MARKET DATA
        # =========================
        ask, bid, spread_pct = get_prices(symbol)
        position = get_position(symbol)
        is_long = position is not None

        print(f"{symbol} | {signal} | pos={is_long} | spread={spread_pct:.4f}", flush=True)

        # =========================
        # LONG ENTRY
        # =========================
        if signal == "LONG":

            if is_long:
                return jsonify({"status": "already_long"}), 200

            cancel_open_order(symbol)

            try:
                if USE_MARKET_ORDERS:
                    api.submit_order(
                        symbol=symbol,
                        qty=qty,
                        side="buy",
                        type="market",
                        time_in_force="day"
                    )
                else:
                    price = ask * (1 + offset)
                    api.submit_order(
                        symbol=symbol,
                        qty=qty,
                        side="buy",
                        type="limit",
                        time_in_force="day",
                        limit_price=round(price, 2),
                        extended_hours=True
                    )

                state["last_trade_time"] = now()

                return jsonify({"status": "long_executed"})

            except Exception as e:
                print("ORDER ERROR:", str(e), flush=True)
                return jsonify({"error": str(e)}), 500

        # =========================
        # EXIT LONG
        # =========================
        if signal == "EXIT LONG":

            if not is_long:
                return jsonify({"status": "no_position"}), 200

            cancel_open_order(symbol)

            actual_qty = abs(float(position.qty))

            try:
                if USE_MARKET_ORDERS:
                    api.submit_order(
                        symbol=symbol,
                        qty=actual_qty,
                        side="sell",
                        type="market",
                        time_in_force="day"
                    )
                else:
                    price = bid * (1 - offset)
                    api.submit_order(
                        symbol=symbol,
                        qty=actual_qty,
                        side="sell",
                        type="limit",
                        time_in_force="day",
                        limit_price=round(price, 2),
                        extended_hours=True
                    )

                state["last_trade_time"] = now()

                return jsonify({"status": "exit_executed"})

            except Exception as e:
                print("ORDER ERROR:", str(e), flush=True)
                return jsonify({"error": str(e)}), 500

    except Exception as e:
        print("ERROR:", str(e), flush=True)
        return jsonify({"error": str(e)}), 500