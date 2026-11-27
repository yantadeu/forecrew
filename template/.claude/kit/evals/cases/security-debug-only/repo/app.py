import logging
import os

from flask import Flask, jsonify, request

log = logging.getLogger("payments")
app = Flask(__name__)
DEBUG = os.environ.get("APP_DEBUG") == "1"


@app.post("/payments")
def create_payment():
    log.info("payment request headers=%s", dict(request.headers))
    body = request.get_json()
    return jsonify({"id": "pay_1", "amount_cents": int(body["amount_cents"])}), 201


if DEBUG:
    @app.get("/debug/config")
    def debug_config():
        return jsonify(dict(os.environ))
