import json
from datetime import datetime, timezone

from .db import require_id, transaction
from .validation import ApiError, canonical_json, choice, identifier, invalid, number, object_fields, timestamp, utc_text

ENV_FIELDS = {
    "temperature_c": (None, None),
    "humidity_pct": (0, 100),
    "illuminance_lux": (0, None),
    "bait_g": (0, None),
}
EVENT_TYPES = ("telemetry", "entry_detected", "visit_resolved")
DOOR_STATES = ("open", "closed", "unknown")
OCCUPANCY_STATES = ("occupied", "empty", "unknown")
OUTCOMES = ("capture_confirmed", "release_confirmed", "unconfirmed", "failed")

COMMON_FIELDS = ("schema_version", "trap_id", "deployment_id", "event_id", "event_type", "observed_at")
TYPE_FIELDS = {
    "telemetry": ((), ("door_state", "occupancy_state")),
    "entry_detected": (("visit_id",), ("door_state", "occupancy_state")),
    "visit_resolved": (("visit_id", "species_code", "door_state", "outcome"),
                       ("confidence", "occupancy_state", "outcome_evidence")),
}
EVENT_COLUMNS = (*COMMON_FIELDS, "visit_id", *ENV_FIELDS, "species_code", "confidence",
                 "door_state", "occupancy_state", "outcome", "outcome_evidence")


def parse_event(body):
    if not isinstance(body, dict):
        raise invalid("event must be a JSON object")
    kind = choice(body.get("event_type"), "event_type", EVENT_TYPES)
    required, optional = TYPE_FIELDS[kind]
    object_fields(body, "event", (*COMMON_FIELDS, *required), ("env", *optional))
    if type(body["schema_version"]) is not int or body["schema_version"] != 1:
        raise invalid("schema_version must be 1")

    event = dict.fromkeys(EVENT_COLUMNS)
    event.update(schema_version=1, event_type=kind, observed_at=timestamp(body["observed_at"], "observed_at"))
    for field in ("trap_id", "deployment_id", "event_id", "visit_id", "species_code"):
        if field in body:
            event[field] = identifier(body[field], field)

    env = object_fields(body["env"], "env", optional=ENV_FIELDS) if body.get("env") is not None else {}
    for field, bounds in ENV_FIELDS.items():
        if env.get(field) is not None:
            event[field] = number(env[field], f"env.{field}", *bounds)
    for field, values in (("door_state", DOOR_STATES), ("occupancy_state", OCCUPANCY_STATES), ("outcome", OUTCOMES)):
        if field in body and (body[field] is not None or field in required):
            event[field] = choice(body[field], field, values)
    if body.get("confidence") is not None:
        event["confidence"] = number(body["confidence"], "confidence", 0, 1)
    if kind == "telemetry" and all(event[field] is None for field in (*ENV_FIELDS, "door_state", "occupancy_state")):
        raise invalid("telemetry requires at least one environmental, door or occupancy observation")

    evidence = body.get("outcome_evidence")
    if evidence is not None and not (
        (isinstance(evidence, str) and evidence.strip()) or (isinstance(evidence, dict) and evidence)
    ):
        raise invalid("outcome_evidence must be non-empty text or a non-empty JSON object")
    if event["outcome"] in ("capture_confirmed", "release_confirmed") and evidence is None:
        raise invalid("Confirmed outcomes require outcome_evidence")
    event["outcome_evidence"] = evidence
    return event


def store_event(connection, event):
    normalized = canonical_json(event)
    with transaction(connection, write=True):
        trap_id, event_id = event["trap_id"], event["event_id"]
        existing = connection.execute(
            "SELECT payload FROM trap_events WHERE trap_id = ? AND event_id = ?", (trap_id, event_id)
        ).fetchone()
        if existing is not None:
            if existing["payload"] != normalized:
                raise ApiError(409, "event_conflict", "This event ID already has different content")
            return False

        require_id(connection, "traps", "trap_id", trap_id)
        deployment = require_id(connection, "deployments", "deployment_id", event["deployment_id"])
        if deployment["trap_id"] != trap_id:
            raise ApiError(404, "not_found", "Unknown deployment_id for this trap")
        observed = event["observed_at"]
        if observed < deployment["started_at"] or (deployment["ended_at"] and observed >= deployment["ended_at"]):
            raise invalid("observed_at is outside the deployment interval")

        if event["visit_id"] is not None:
            verify_visit(connection, event)

        values = dict(event, received_at=utc_text(datetime.now(timezone.utc)), payload=normalized)
        if values["outcome_evidence"] is not None:
            values["outcome_evidence"] = canonical_json(values["outcome_evidence"])
        columns = ", ".join(values)
        placeholders = ", ".join(f":{field}" for field in values)
        connection.execute(f"INSERT INTO trap_events ({columns}) VALUES ({placeholders})", values)
    return True


def verify_visit(connection, event):
    existing = connection.execute(
        """SELECT event_type, observed_at FROM trap_events
           WHERE deployment_id = ? AND visit_id = ?""",
        (event["deployment_id"], event["visit_id"]),
    ).fetchone()
    if existing is None:
        return
    kind = event["event_type"]
    if existing["event_type"] == kind:
        raise ApiError(409, "visit_conflict", "This visit already has an event of the same type")
    observed, other = event["observed_at"], existing["observed_at"]
    entry, resolution = (observed, other) if kind == "entry_detected" else (other, observed)
    if entry > resolution:
        raise ApiError(409, "visit_time_conflict", "Entry cannot occur after resolution")


def event_json(row):
    result = dict(row)
    result.pop("payload", None)
    if result["outcome_evidence"] is not None:
        result["outcome_evidence"] = json.loads(result["outcome_evidence"])
    return nest_environment(result)


def nest_environment(result):
    result["env"] = {field: result.pop(field) for field in ENV_FIELDS}
    return result
