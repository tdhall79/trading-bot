@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # DEBUG (safe here)
        print("RAW:", request.data)

        data = request.get_json(force=True, silent=True)
        print("PARSED:", data)

        if not data:
            return jsonify({"status": "error", "message": "No JSON"}), 400

        symbol = data.get("symbol")
        action = data.get("action")

        qty = int(float(data.get("quantity", 0)))

        limit_price = data.get("limit_price")
        if limit_price is not None:
            limit_price = float(limit_price)

        if not symbol or not action or qty <= 0:
            return jsonify({
                "status": "error",
                "message": "Bad fields",
                "data": data
            }), 400

        positions = {p.symbol: p for p in api.list_positions()}
        position = positions.get(symbol)

        if action == "buy" and position:
            return jsonify({"status": "skip", "reason": "already in position"})

        if action == "sell" and not position:
            return jsonify({"status": "skip", "reason": "no position"})

        order = api.submit_order(
            symbol=symbol,
            qty=qty,
            side=action,
            type=data.get("type", "limit"),
            time_in_force=data.get("time_in_force", "day"),
            limit_price=limit_price,
            extended_hours=data.get("extended_hours", True)
        )

        return jsonify({"status": "ok", "order_id": order.id})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400
