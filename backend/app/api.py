import hmac
import sqlite3
from pathlib import Path

from flask import Blueprint, abort, current_app, request, send_from_directory

from . import events, queries, recommendations
from .db import detach_db, get_db
from .validation import ApiError, json_body

api = Blueprint("api", __name__, url_prefix="/api")
health = Blueprint("health", __name__)


@health.get("/health")
def health_check():
    try:
        get_db().execute("SELECT trap_id FROM traps LIMIT 1").fetchone()
    except sqlite3.Error:
        return {"status": "unavailable"}, 503
    return {"status": "ok"}


@api.after_request
def disable_api_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def authorize(role):
    # TRAP_READ_AUTH=off: GET 조회는 토큰 없이 허용한다(같은 LAN의 대시보드용). 쓰기 API는 항상 토큰이 필요하다.
    if role == "read" and current_app.config["READ_AUTH"] == "off":
        return None
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token or not token.isascii():
        raise ApiError(401, "unauthorized", "A valid bearer token is required")

    config = current_app.config
    grants = [("read", None, config["READ_TOKEN"]), ("recommendation", None, config["RECOMMENDATION_TOKEN"])]
    grants.extend(("device", device_id, key) for device_id, key in config["DEVICE_TOKENS"].items())
    for grant_role, device_id, key in grants:
        if key and hmac.compare_digest(key, token):
            if role == grant_role:
                return device_id
            raise ApiError(403, "forbidden", "This token cannot perform the requested action")
    raise ApiError(401, "unauthorized", "A valid bearer token is required")


@api.post("/sensor/data")
def ingest():
    device_id = authorize("device")
    event = events.parse_event(json_body())
    if device_id != event["trap_id"]:
        raise ApiError(403, "forbidden", "This token is not assigned to the requested trap")
    created = events.store_event(get_db(), event)
    return {"event_id": event["event_id"], "duplicate": not created}, 201 if created else 200


@api.get("/traps")
def traps():
    authorize("read")
    return queries.traps(get_db())


@api.get("/deployments")
def deployments():
    authorize("read")
    return queries.deployments(get_db())


@api.get("/traps/<trap_id>/status")
def trap_status(trap_id):
    authorize("read")
    return queries.trap_status(get_db(), trap_id)


@api.get("/locations")
def locations():
    authorize("read")
    return queries.locations(get_db())


@api.get("/readings")
def readings():
    authorize("read")
    return queries.readings(get_db())


@api.get("/visits")
def visits():
    authorize("read")
    return queries.visits(get_db())


@api.get("/captures")
def captures():
    authorize("read")
    return queries.captures(get_db())


@api.get("/stats/daily")
def daily():
    authorize("read")
    return queries.daily_stats(get_db())


@api.get("/export/events.csv")
def export_events():
    authorize("read")
    response = queries.export_csv(get_db())
    # The response keeps reading its cursor after Flask tears down the request.
    response.call_on_close(detach_db().close)
    return response


@api.post("/recommendations")
def add_recommendation():
    authorize("recommendation")
    run = recommendations.parse_run(json_body())
    created = recommendations.store_run(get_db(), run)
    return {"run_id": run["run_id"], "duplicate": not created}, 201 if created else 200


@api.get("/recommendations")
def recommendation_history():
    authorize("read")
    return recommendations.list_runs(get_db())


@api.get("/recommendations/latest")
def recommendation_latest():
    authorize("read")
    return recommendations.latest_run(get_db())


def register_dashboard(app):
    configured = app.config["DASHBOARD_DIR"]
    if not configured:
        return
    directory = Path(configured).resolve()
    if not (directory / "index.html").is_file():
        raise RuntimeError("TRAP_DASHBOARD_DIR must contain index.html")

    @app.get("/")
    def dashboard():
        return send_from_directory(directory, "index.html")

    @app.get("/<path:asset>")
    def dashboard_asset(asset):
        if asset == "api" or asset.startswith("api/"):
            abort(404)
        return send_from_directory(directory, asset)
