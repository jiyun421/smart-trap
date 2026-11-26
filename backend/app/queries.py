import csv
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Response, request

from .db import require_id, transaction
from .events import ENV_FIELDS, event_json, nest_environment
from .validation import identifier, invalid, time_range, utc_text


def traps(connection):
    rows = connection.execute(
        """SELECT t.*, d.deployment_id, d.location_id, d.target_species, d.started_at
           FROM traps t LEFT JOIN deployments d ON d.trap_id = t.trap_id AND d.ended_at IS NULL
           ORDER BY t.trap_id"""
    )
    return {"items": [dict(row) for row in rows]}


def deployments(connection):
    """설치 이력(재배치 이력 포함). 종료되지 않은 설치는 ended_at이 null이다."""
    conditions, params = filter_trap(connection, "trap_id")
    sql = "SELECT * FROM deployments" + where_sql(conditions)
    rows = connection.execute(sql + " ORDER BY started_at, deployment_id", params)
    return {"items": [dict(row) for row in rows]}


def locations(connection):
    rows = connection.execute(
        """SELECT l.*, (SELECT COUNT(*) FROM deployments d
                          WHERE d.location_id = l.location_id AND d.ended_at IS NULL) AS active_traps
           FROM locations l ORDER BY l.location_id"""
    )
    return {"items": [dict(row) for row in rows]}


def trap_status(connection, trap_id):
    with transaction(connection):
        trap = require_id(connection, "traps", "trap_id", trap_id)
        deployment = connection.execute(
            "SELECT * FROM deployments WHERE trap_id = ? AND ended_at IS NULL", (trap_id,)
        ).fetchone()
        deployment_id = deployment["deployment_id"] if deployment is not None else None
        latest = connection.execute(
            "SELECT MAX(observed_at) AS observed, MAX(received_at) AS received FROM trap_events WHERE deployment_id = ?",
            (deployment_id,),
        ).fetchone()
        capture = connection.execute(
            """SELECT * FROM trap_events WHERE deployment_id = ? AND event_type = 'visit_resolved'
               AND outcome = 'capture_confirmed' ORDER BY observed_at DESC, event_id DESC LIMIT 1""",
            (deployment_id,),
        ).fetchone()
        now = datetime.now(timezone.utc)
        max_age = 3 * trap["report_interval_seconds"]
        measurements = {}
        for field in (*ENV_FIELDS, "door_state", "occupancy_state"):
            row = connection.execute(
                f"""SELECT {field}, observed_at FROM trap_events WHERE deployment_id = ? AND {field} IS NOT NULL
                    ORDER BY observed_at DESC, event_id DESC LIMIT 1""",
                (deployment_id,),
            ).fetchone()
            observed = row["observed_at"] if row else None
            age = age_seconds(now, observed)
            measurements[field] = {
                "value": row[field] if row else None, "observed_at": observed,
                "age_seconds": age, "stale": age is not None and age > max_age,
            }

    bait = measurements["bait_g"]
    bait_status = "unknown"
    if bait["value"] is not None and not bait["stale"]:
        if bait["value"] <= trap["empty_g"]:
            bait_status = "empty"
        elif bait["value"] <= trap["low_g"]:
            bait_status = "low"
        else:
            bait_status = "ok"

    received_age = age_seconds(now, latest["received"])
    connection_state = "unknown" if received_age is None else "online" if received_age <= max_age else "offline"
    return {
        "trap_id": trap_id, "deployment": dict(deployment) if deployment else None,
        "report_interval_seconds": trap["report_interval_seconds"], "stale_after_seconds": max_age,
        "last_observed_at": latest["observed"], "last_received_at": latest["received"],
        "connection_state": connection_state, "observations": measurements, "bait_status": bait_status,
        "recent_capture": event_json(capture) if capture else None,
    }


def parse_utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def age_seconds(now, value):
    return max(0, int((now - parse_utc(value)).total_seconds())) if value is not None else None


def filter_trap(connection, column="e.trap_id"):
    trap_id = request.args.get("trap_id")
    if trap_id is None:
        return [], []
    require_id(connection, "traps", "trap_id", identifier(trap_id, "trap_id"))
    return [f"{column} = ?"], [trap_id]


def add_period(conditions, params, column, bounds):
    for operator, value in zip((">=", "<"), bounds):
        if value is not None:
            conditions.append(f"{column} {operator} ?")
            params.append(value)


def where_sql(conditions):
    return " WHERE " + " AND ".join(conditions) if conditions else ""


def page_parameters():
    def parameter(field, default, lower, upper):
        value = request.args.get(field, str(default))
        if len(value) > 10 or not value.isascii() or not value.isdecimal() or not lower <= int(value) <= upper:
            raise invalid(f"{field} must be an integer from {lower} to {upper}")
        return int(value)

    return parameter("limit", 100, 1, 500), parameter("offset", 0, 0, 1_000_000_000)


def fetch_page(connection, sql, params):
    limit, offset = page_parameters()
    rows = connection.execute(sql + " LIMIT ? OFFSET ?", (*params, limit + 1, offset)).fetchall()
    return rows[:limit], offset + limit if len(rows) > limit else None


def requested_range():
    return time_range(request.args.get("from"), request.args.get("to"))


def bounded_range(max_days, default_days=None):
    start, end = requested_range()
    if start is None and end is None and default_days is not None:
        now = datetime.now(timezone.utc)
        return utc_text(now - timedelta(days=default_days)), utc_text(now)
    if start is None or end is None:
        raise invalid("Supply both from and to")
    if parse_utc(end) - parse_utc(start) > timedelta(days=max_days):
        raise invalid(f"The requested range cannot exceed {max_days} days")
    return start, end


def readings(connection):
    conditions, params = filter_trap(connection)
    conditions.append("(" + " OR ".join(f"e.{field} IS NOT NULL" for field in ENV_FIELDS) + ")")
    return event_page(connection, conditions, params)


def captures(connection):
    conditions, params = filter_trap(connection)
    conditions.extend(("e.event_type = 'visit_resolved'", "e.outcome = 'capture_confirmed'"))
    return event_page(connection, conditions, params)


def event_page(connection, conditions, params):
    add_period(conditions, params, "e.observed_at", requested_range())
    sql = """SELECT e.*, d.location_id, d.target_species FROM trap_events e
             JOIN deployments d ON d.deployment_id = e.deployment_id""" + where_sql(conditions)
    rows, next_offset = fetch_page(connection, sql + " ORDER BY e.observed_at DESC, e.trap_id, e.event_id", params)
    return {"items": [event_json(row) for row in rows], "next_offset": next_offset}


def visits(connection):
    conditions, params = filter_trap(connection, "v.trap_id")
    add_period(conditions, params, "v.observed_at", requested_range())
    species_code = request.args.get("species_code")
    if species_code is not None:
        conditions.append("v.species_code = ?")
        params.append(identifier(species_code, "species_code"))
    sql = """WITH visits AS (
                 SELECT base.trap_id, base.deployment_id, base.visit_id, base.observed_at,
                        d.location_id, d.target_species, resolution.species_code,
                        entry.payload AS entry_payload, entry.received_at AS entry_received,
                        resolution.payload AS resolved_payload, resolution.received_at AS resolved_received
                 FROM trap_events base
                 JOIN deployments d ON d.deployment_id = base.deployment_id
                 LEFT JOIN trap_events entry ON entry.deployment_id = base.deployment_id
                    AND entry.visit_id = base.visit_id AND entry.event_type = 'entry_detected'
                 LEFT JOIN trap_events resolution ON resolution.deployment_id = base.deployment_id
                    AND resolution.visit_id = base.visit_id AND resolution.event_type = 'visit_resolved'
                 WHERE base.event_type = 'entry_detected'
                    OR (base.event_type = 'visit_resolved' AND entry.event_id IS NULL)
             ) SELECT v.* FROM visits v""" + where_sql(conditions)
    rows, next_offset = fetch_page(connection, sql + " ORDER BY v.observed_at DESC, v.deployment_id, v.visit_id", params)
    items = []
    for row in rows:
        item = dict(row)
        for prefix, key in (("entry", "entry"), ("resolved", "resolution")):
            payload = item.pop(f"{prefix}_payload")
            received = item.pop(f"{prefix}_received")
            item[key] = nest_environment(dict(json.loads(payload), received_at=received)) if payload else None
        items.append(item)
    return {"items": items, "next_offset": next_offset}


def daily_stats(connection):
    tz_name = request.args.get("tz", "Asia/Seoul")
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise invalid("tz must be an IANA timezone name") from None
    conditions, params = filter_trap(connection)
    add_period(conditions, params, "e.observed_at", bounded_range(366, default_days=7))
    conditions.append("(e.event_type = 'entry_detected' OR e.outcome = 'capture_confirmed')")
    sql = """SELECT e.trap_id, e.observed_at, e.event_type, d.target_species,
                     COALESCE(e.species_code, r.species_code) AS species_code
              FROM trap_events e JOIN deployments d ON d.deployment_id = e.deployment_id
              LEFT JOIN trap_events r ON e.event_type = 'entry_detected' AND r.deployment_id = e.deployment_id
                 AND r.visit_id = e.visit_id AND r.event_type = 'visit_resolved'""" + where_sql(conditions)
    buckets = {}
    for row in connection.execute(sql, params):
        try:
            day = parse_utc(row["observed_at"]).astimezone(tz).date().isoformat()
        except OverflowError:
            raise invalid("A timestamp cannot be represented in the requested timezone") from None
        key = (day, row["trap_id"])
        bucket = buckets.setdefault(key, {
            "date": day, "trap_id": row["trap_id"], "entries": 0, "target_entries": 0,
            "confirmed_captures": 0, "non_target_captures": 0, "unclassified_entries": 0,
            "pending_entries": 0, "unclassified_captures": 0,
        })
        species = row["species_code"]
        if row["event_type"] == "entry_detected":
            bucket["entries"] += 1
            bucket["target_entries"] += species == row["target_species"]
            bucket["unclassified_entries"] += species == "unknown"
            bucket["pending_entries"] += species is None
        else:
            bucket["confirmed_captures"] += 1
            bucket["unclassified_captures"] += species == "unknown"
            bucket["non_target_captures"] += species not in ("unknown", row["target_species"])
    return {"timezone": tz_name, "items": [buckets[key] for key in sorted(buckets)]}


CSV_COLUMNS = (
    "schema_version", "trap_id", "deployment_id", "location_id", "visit_id", "event_id", "event_type",
    "observed_at", "received_at", "target_species", "species_code", "confidence", *ENV_FIELDS,
    "door_state", "occupancy_state", "outcome", "outcome_evidence",
)


def export_csv(connection):
    conditions, params = filter_trap(connection)
    add_period(conditions, params, "e.observed_at", bounded_range(31))
    sql = """SELECT e.*, d.location_id, d.target_species FROM trap_events e
             JOIN deployments d ON d.deployment_id = e.deployment_id""" + where_sql(conditions)
    cursor = connection.execute(sql + " ORDER BY e.observed_at, e.trap_id, e.event_id", params)

    class CsvBuffer:
        def write(self, value):
            return value

    def generate():
        writer = csv.writer(CsvBuffer())
        try:
            yield writer.writerow(CSV_COLUMNS)
            for row in cursor:
                yield writer.writerow(row[column] for column in CSV_COLUMNS)
        finally:
            cursor.close()

    return Response(generate(), content_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="events.csv"',
    })
