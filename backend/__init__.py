"""Create and configure the Scholarly Insight Flask application."""

from flask import Flask
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from backend.api.errors import handle_http_error
from backend.api.routes import api as api_blueprint


def create_app():
    """Build an application with the public API and JSON error handlers."""
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False
    CORS(app, resources={r"/api/(search|health)$": {"origins": "*", "methods": ["GET"]}})
    app.register_blueprint(api_blueprint)
    app.register_error_handler(HTTPException, handle_http_error)
    return app
