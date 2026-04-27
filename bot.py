 @app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # --- Robust JSON parsing (fixes 415/400 issues) ---
        data = request.get_json(force=True, silent=True)

        if not data:
            return jsonify({"status": "error", "message": "No JSON received"}), 400

        # --- Extract + sanitize fields ---
        symbol = data.get("symbol")
        action = data.get("action")

        try:
            qty = int(float(data.get("quantity", 0)))
        except:
            qty = 0

        try:
            limit_price = float(data.get("limit_price")) if data.get("limit_price") is not None else None
        except:
            limit_price = None

        order_type = data.get("type", "limit")
        tif = data.get("time_in_force", "day")
        extended = data.get("extended_hours", True)

        # --- Validate payload ---
        if not symbol or not action or qty <= 0:
            return jsonify({
                "status": "error",
                "message": "Invalid payload",
                "received": data
            }), 400

        # --- Position check ---
        positions = {p.symbol: p for p in api.list_positions()}
        position = positions.get(symbol)

        if action == "buy" and position:
            return jsonify({"status": "skipped", "reason": "already in position"})

        if action == "sell" and not position:
            return jsonify({"status": "skipped", "reason": "no position"})

        # --- Submit order ---
        order = api.submit_order(
            symbol=symbol,
            qty=qty,
            side=action,
            type=order_type,
            time_in_force=tif,
            limit_price=limit_price,
            extended_hours=extended
        )

        return jsonify({
            "status": "success",
            "symbol": symbol,
            "side": action,
            "qty": qty,
            "order_id": order.id
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
