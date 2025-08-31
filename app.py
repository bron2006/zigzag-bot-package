# app.py
import logging, os, requests
from flask import Flask, jsonify, send_from_directory, Response, request

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("webapp")

app = Flask(__name__)
WEBAPP_DIR = os.path.join(app.root_path, "webapp")
WORKER_URL = "http://localhost:8081"

@app.route("/")
def home(): return send_from_directory(WEBAPP_DIR, 'index.html')

@app.route("/<path:filename>")
def static_files(filename): return send_from_directory(WEBAPP_DIR, filename)

def proxy_request(method, path, **kwargs):
    try:
        url = f"{WORKER_URL}{path}"
        resp = requests.request(method, url, **kwargs)
        resp.raise_for_status()
        
        # For SSE stream
        if 'text/event-stream' in resp.headers.get('Content-Type', ''):
            return Response(resp.iter_content(chunk_size=1024), content_type=resp.headers['Content-Type'])
            
        return jsonify(resp.json())
    except requests.RequestException as e:
        logger.error(f"Proxy request to {path} failed: {e}")
        return jsonify({"error": "Worker service unavailable"}), 503

@app.route("/api/get_pairs")
def get_pairs(): return proxy_request(method='GET', path='/get_pairs')

@app.route("/api/scanner/status")
def get_scanner_status(): return proxy_request(method='GET', path='/status')

@app.route("/api/scanner/toggle", methods=['POST'])
def toggle_scanner(): return proxy_request(method='POST', path='/toggle_scanner', json=request.json)

@app.route("/api/signal")
def api_signal(): return proxy_request(method='GET', path='/analyze', params=request.args)

@app.route("/api/signal-stream")
def signal_stream(): return proxy_request(method='GET', path='/signal-stream', stream=True, timeout=None)