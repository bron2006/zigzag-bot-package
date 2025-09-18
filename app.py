# app.py
import os
import logging
from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS
from dotenv import load_dotenv
from waitress import serve

# Load environment variables
load_dotenv()

# Import project modules
import db
import bot
import ctrader
import scanner
import api
from auth import auth_debugger, init_data_valid
from state import state_manager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Initialize Flask app
app = Flask(__name__, static_folder='webapp', static_url_path='')
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default-secret-key-for-development')
CORS(app)

# Register API blueprints
app.register_blueprint(api.bp)

# Serve the main web application
@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

# Main function to run the application
def main():
    # Initialize database
    try:
        db.initialize_database()
    except Exception as e:
        logging.error(f"Error initializing database: {e}")

    # Initialize and start other services
    bot.init_bot()
    ctrader.init_ctrader()
    scanner.init_scanner()
    
    # Run the web server using waitress, listening on all interfaces
    port = int(os.environ.get('PORT', 8080))
    logging.info(f"Waitress server listening on 0.0.0.0:{port}")
    serve(app, host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()