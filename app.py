# app.py
import logging
import os
import json
import requests
from flask import Flask, jsonify, send_from_directory, Response, request

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("webapp")

app = Flask(__name__)
WEBAPP_DIR = os.path.join(app.root_path, "webapp")
WORKER_URL = "http://localhost:8081"

# --- Static Files Serving ---
@app.route("/")
def home():
    return send_from_directory(WEBAPP_DIR, 'index.html')

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEBAPP_DIR, filename)

# --- API Proxy Routes ---
@app.route("/api/scanner/status")
def get_scanner_status():
    try:
        resp = requests.get(f"{WORKER_URL}/status", timeout=5)
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.RequestException as e:
        return jsonify({"error": "Worker service unavailable"}), 503

@app.route("/api/scanner/toggle", methods=['POST'])
def toggle_scanner():
    try:
        resp = requests.post(f"{WORKER_URL}/toggle_scanner", json=request.json, timeout=5)
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.RequestException as e:
        return jsonify({"error": "Worker service unavailable"}), 503

@app.route("/api/signal")
def api_signal():
    try:
        resp = requests.get(f"{WORKER_URL}/analyze", params=request.args, timeout=20)
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.RequestException as e:
        return jsonify({"error": "Worker service unavailable"}), 503

@app.route("/api/signal-stream")
def signal_stream():
    try:
        req = requests.get(f"{WORKER_URL}/signal-stream", stream=True, timeout=None)
        return Response(req.iter_content(chunk_size=1024), content_type=req.headers['Content-Type'])
    except requests.RequestException as e:
        logger.error(f"Could not connect to worker for SSE stream: {e}")
        return "Stream unavailable", 503

# MODIFIED: Renamed from /api/get_assets to /api/get_pairs
@app.route("/api/get_pairs")
def get_pairs():
    try:
        resp = requests.get(f"{WORKER_URL}/get_pairs", timeout=5)
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.RequestException as e:
        return jsonify({"error": "Worker service unavailable"}), 503