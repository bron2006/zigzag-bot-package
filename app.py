# app.py
import logging
import os
import json
import requests

from flask import Flask, jsonify, send_from_directory, Response, request

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("webapp")

app = Flask(__name__)
WEBAPP_DIR = os.path.join(os.path.dirname(__file__), "webapp")

# The worker's internal address. 'localhost' works because both processes run on the same Fly machine.
WORKER_URL = "http://localhost:8081"

# --- Routes ---
@app.route("/")
def home():
    try:
        filepath = os.path.join(WEBAPP_DIR, 'index.html')
        with open(filepath, "r", encoding="utf-8") as f: content = f.read()
        return Response(content, mimetype='text/html')
    except Exception as e:
        return "Internal Server Error", 500

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEBAPP_DIR, filename)

# --- API Proxy Routes ---
# All /api/* routes will now proxy requests to the worker

@app.route("/api/scanner/status")
def get_scanner_status():
    try:
        resp = requests.get(f"{WORKER_URL}/status", timeout=5)
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.RequestException as e:
        logger.error(f"Could not connect to worker for status: {e}")
        return jsonify({"error": "Worker service unavailable"}), 503

@app.route("/api/scanner/toggle", methods=['POST'])
def toggle_scanner():
    try:
        data = request.json
        resp = requests.post(f"{WORKER_URL}/toggle_scanner", json=data, timeout=5)
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.RequestException as e:
        logger.error(f"Could not connect to worker to toggle scanner: {e}")
        return jsonify({"error": "Worker service unavailable"}), 503

@app.route("/api/signal")
def api_signal():
    pair = request.args.get("pair")
    try:
        resp = requests.get(f"{WORKER_URL}/analyze", params={"pair": pair}, timeout=20)
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.RequestException as e:
        logger.error(f"Could not connect to worker for on-demand analysis: {e}")
        return jsonify({"error": "Worker service unavailable"}), 503

@app.route("/api/signal-stream")
def signal_stream():
    try:
        # Use streaming=True to handle the response as a stream
        req = requests.get(f"{WORKER_URL}/signal-stream", stream=True, timeout=60)
        
        def generate():
            for chunk in req.iter_content(chunk_size=1024):
                yield chunk

        return Response(generate(), content_type=req.headers['Content-Type'])
    except requests.RequestException as e:
        logger.error(f"Could not connect to worker for SSE stream: {e}")
        # Cannot return a JSON error for a stream, so we just log it.
        return "Stream unavailable", 503