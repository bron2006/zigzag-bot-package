# app.py
import logging, os, requests
from flask import Flask, jsonify, send_from_directory, Response, request

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
WEBAPP_DIR = os.path.join(app.root_path, "webapp")
WORKER_URL = "http://localhost:8081"

@app.route("/")
def home(): return send_from_directory(WEBAPP_DIR, 'index.html')

@app.route("/<path:filename>")
def static_files(filename): return send_from_directory(WEBAPP_DIR, filename)

def proxy(path, **kwargs):
    try:
        resp = requests.request(request.method, f"{WORKER_URL}{path}", **kwargs)
        resp.raise_for_status()
        if 'text/event-stream' in resp.headers.get('Content-Type', ''):
            return Response(resp.iter_content(chunk_size=1024), content_type=resp.headers['Content-Type'])
        return jsonify(resp.json())
    except requests.RequestException: return jsonify({"error": "Сервіс недоступний"}), 503

@app.route("/api/get_pairs")
def get_pairs(): return proxy('/get_pairs')

@app.route("/api/scanner/status")
def status(): return proxy('/status')

@app.route("/api/scanner/toggle", methods=['POST'])
def toggle(): return proxy('/toggle_scanner', json=request.json)

@app.route("/api/signal")
def signal(): return proxy('/analyze', params=request.args)

@app.route("/api/signal-stream")
def stream(): return proxy('/signal-stream', stream=True, timeout=None)