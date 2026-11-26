import json
import os
from pathlib import Path

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from . import db
from .api import api, health, register_dashboard
from .validation import IDENTIFIER, ApiError, unique_object


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        DB_PATH=os.environ.get("TRAP_DB_PATH", str(Path(app.instance_path) / "traps.sqlite3")),
        DEVICE_TOKENS=os.environ.get("TRAP_DEVICE_TOKENS", "{}"),
        READ_TOKEN=os.environ.get("TRAP_READ_TOKEN", ""),
        RECOMMENDATION_TOKEN=os.environ.get("TRAP_RECOMMENDATION_TOKEN", ""),
        READ_AUTH=os.environ.get("TRAP_READ_AUTH", "required"),
        DASHBOARD_DIR=os.environ.get("TRAP_DASHBOARD_DIR"),
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if config is not None:
        app.config.update(config)
    configure_tokens(app)
    db.init_app(app)
    app.register_blueprint(health)
    app.register_blueprint(api)
    register_dashboard(app)

    @app.errorhandler(ApiError)
    def api_error(error):
        headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 else {}
        return {"error": {"code": error.code, "message": error.message}}, error.status, headers

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path == "/api" or request.path.startswith("/api/"):
            response = error.get_response()
            response.set_data(app.json.dumps({
                "error": {"code": error.name.lower().replace(" ", "_"), "message": error.description}
            }))
            response.mimetype = "application/json"
            return response
        return error

    return app


def configure_tokens(app):
    if app.config["READ_AUTH"] not in ("required", "off"):
        raise RuntimeError("TRAP_READ_AUTH must be 'required' or 'off'")
    devices = app.config["DEVICE_TOKENS"]
    if isinstance(devices, str):
        try:
            devices = json.loads(devices, object_pairs_hook=unique_object)
        except ValueError:
            raise RuntimeError("TRAP_DEVICE_TOKENS must be a JSON object") from None
    if not isinstance(devices, dict) or not all(
        isinstance(trap, str) and IDENTIFIER.fullmatch(trap) and isinstance(token, str) and token
        for trap, token in devices.items()
    ):
        raise RuntimeError("TRAP_DEVICE_TOKENS must map trap IDs to non-empty tokens")
    tokens = [*devices.values(), app.config["READ_TOKEN"], app.config["RECOMMENDATION_TOKEN"]]
    tokens = [token for token in tokens if token]
    if any(not isinstance(token, str) or not token.isascii() or not token.isprintable()
           or any(char.isspace() for char in token) for token in tokens):
        raise RuntimeError("Tokens must be printable ASCII without whitespace")
    if len(tokens) != len(set(tokens)):
        raise RuntimeError("Use distinct tokens for each trap and API role")
    app.config["DEVICE_TOKENS"] = devices
