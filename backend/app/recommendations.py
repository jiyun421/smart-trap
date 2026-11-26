import json

from flask import request

from .db import require_id, transaction
from .queries import fetch_page, filter_trap, where_sql
from .validation import (
    ApiError, canonical_json, choice, identifier, integer, invalid, nonempty_text, number, object_fields,
    time_range, timestamp,
)

PREDICTION_KINDS = ("target_entry", "target_capture")
SCORE_TYPES = ("probability", "relative_score")
RUN_COLUMNS = (
    "run_id", "trap_id", "target_species", "model_version", "generated_at", "prediction_kind",
    "data_from", "data_to", "forecast_from", "forecast_to", "status",
)
MAX_CANDIDATES = 500


def parse_run(body):
    object_fields(body, "run", (*RUN_COLUMNS, "candidates"), ("score_type", "reason"))
    result = {field: identifier(body[field], field) for field in ("run_id", "trap_id", "target_species")}
    if result["target_species"] == "unknown":
        raise invalid("target_species must be a known species code")
    result["model_version"] = nonempty_text(body["model_version"], "model_version", 128)
    result["generated_at"] = timestamp(body["generated_at"], "generated_at")
    result["prediction_kind"] = choice(body["prediction_kind"], "prediction_kind", PREDICTION_KINDS)
    for prefix in ("data", "forecast"):
        start_field, end_field = f"{prefix}_from", f"{prefix}_to"
        start, end = time_range(body[start_field], body[end_field], start_field, end_field)
        if not start or not end:
            raise invalid(f"Both {start_field} and {end_field} are required")
        result.update({start_field: start, end_field: end})

    result["status"] = choice(body["status"], "status", ("ready", "insufficient_data"))
    result["reason"] = nonempty_text(body["reason"], "reason") if body.get("reason") is not None else None
    candidates = body["candidates"]
    if not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATES:
        raise invalid(f"candidates must be an array of up to {MAX_CANDIDATES} items")
    if result["status"] == "insufficient_data":
        if candidates or result["reason"] is None or body.get("score_type") is not None:
            raise invalid("insufficient_data requires a reason, an empty candidates array and no score_type")
        result.update(candidates=[], score_type=None)
        return result

    if not candidates:
        raise invalid("ready requires at least one candidate")
    result["score_type"] = choice(body.get("score_type"), "score_type", SCORE_TYPES)
    candidates = [parse_candidate(candidate) for candidate in candidates]
    for key in ("location_id", "rank"):
        if len({candidate[key] for candidate in candidates}) != len(candidates):
            raise invalid(f"Candidate {key} values must be unique")
    result["candidates"] = sorted(candidates, key=lambda candidate: candidate["rank"])
    return result


def parse_candidate(body):
    object_fields(body, "candidate", ("location_id", "rank", "score", "reason"))
    return {
        "location_id": identifier(body["location_id"], "location_id"),
        "rank": integer(body["rank"], "rank", 1, MAX_CANDIDATES),
        "score": number(body["score"], "score", 0, 1),
        "reason": nonempty_text(body["reason"], "candidate reason"),
    }


def store_run(connection, run):
    normalized = canonical_json(run)
    with transaction(connection, write=True):
        existing = connection.execute(
            "SELECT payload FROM recommendation_runs WHERE run_id = ?", (run["run_id"],)
        ).fetchone()
        if existing is not None:
            if existing["payload"] != normalized:
                raise ApiError(409, "run_conflict", "This run ID already has different content")
            return False

        require_id(connection, "traps", "trap_id", run["trap_id"])
        candidates = run["candidates"]
        if candidates:
            ids = [candidate["location_id"] for candidate in candidates]
            placeholders = ", ".join("?" for _ in ids)
            count = connection.execute(
                f"SELECT COUNT(*) FROM locations WHERE location_id IN ({placeholders})", ids
            ).fetchone()[0]
            if count != len(ids):
                raise ApiError(404, "not_found", "Unknown candidate location_id")

        columns = (*RUN_COLUMNS, "score_type", "reason", "payload")
        names = ", ".join(columns)
        placeholders = ", ".join(f":{name}" for name in columns)
        connection.execute(f"INSERT INTO recommendation_runs ({names}) VALUES ({placeholders})",
                           dict(run, payload=normalized))
        connection.executemany(
            """INSERT INTO recommendation_items (run_id, location_id, rank, score, reason)
               VALUES (:run_id, :location_id, :rank, :score, :reason)""",
            (dict(candidate, run_id=run["run_id"]) for candidate in candidates),
        )
    return True


def run_query(connection):
    conditions, params = filter_trap(connection, "trap_id")
    target = request.args.get("target_species")
    if target is not None:
        conditions.append("target_species = ?")
        params.append(identifier(target, "target_species"))
    kind = request.args.get("prediction_kind")
    if kind is not None:
        conditions.append("prediction_kind = ?")
        params.append(choice(kind, "prediction_kind", PREDICTION_KINDS))
    sql = "SELECT payload FROM recommendation_runs" + where_sql(conditions)
    return sql + " ORDER BY generated_at DESC, run_id DESC", params


def list_runs(connection):
    sql, params = run_query(connection)
    rows, next_offset = fetch_page(connection, sql, params)
    return {"items": [json.loads(row["payload"]) for row in rows], "next_offset": next_offset}


def latest_run(connection):
    sql, params = run_query(connection)
    row = connection.execute(sql + " LIMIT 1", params).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "No recommendation run matches these filters")
    return json.loads(row["payload"])
