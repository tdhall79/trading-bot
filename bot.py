from flask import Flask, request, jsonify
import alpaca_trade_api as tradeapi
import os
from datetime import datetime, time
import pytz
import time as pytime

app = Flask(__name__)

# ==================== PAPER TRADING ====================
api = tradeapi.REST(
    os.getenv("APCA_API_KEY_ID"),
    os.getenv("APCA_API_SECRET_KEY"),
    base_url="https://paper-api.alpaca.markets"   # ← Paper account
)

DEFAULT_NOTIONAL = 7000
EXTENDED_LIMIT_OFFSET = 0.02
TRAILING_STOP_PERCENT = 0.5
