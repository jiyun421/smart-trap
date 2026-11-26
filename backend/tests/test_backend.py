import csv
import io
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.db import apply_migrations, connect
from app.validation import utc_text

DB_START = "2026-01-01T00:00:00Z"
TEST_PERIOD = "from=2026-01-02T00:00:00Z&to=2026-01-03T00:00:00Z"
READ = {"Authorization": "Bearer pc-read"}
WRITE = {"Authorization": "Bearer pc-write"}
DEVICE = {"Authorization": "Bearer trap-1-key"}


class BackendTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "test.sqlite3"
        self.config = {
            "TESTING": True, "DB_PATH": self.path, "DASHBOARD_DIR": None,
            "DEVICE_TOKENS": {"trap-1": "trap-1-key", "trap-2": "trap-2-key"},
            "READ_TOKEN": "pc-read", "RECOMMENDATION_TOKEN": "pc-write",
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.cli("migrate")
        self.cli("registry", "trap", "trap-1", "Trap One", "--empty-g", "2", "--low-g", "10", "--interval", "60")
        self.cli("registry", "location", "a", "Location A")
        self.cli("registry", "location", "b", "Location B")
        self.cli("registry", "deploy", "dep-1", "trap-1", "a", "rat", DB_START)

    def cli(self, *args, status=0):
        result = self.app.test_cli_runner().invoke(args=list(args))
        self.assertEqual(result.exit_code, status, result.output)
        return result.output

    def event(self, event_id, kind="telemetry", observed_at="2026-01-02T14:59:00Z", **fields):
        return dict(schema_version=1, trap_id="trap-1", deployment_id="dep-1", event_id=event_id,
                    event_type=kind, observed_at=observed_at, **fields)

    def send(self, event, status=201, headers=DEVICE):
        response = self.client.post("/api/sensor/data", json=event, headers=headers)
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        return response.get_json()

    def read(self, path, status=200):
        response = self.client.get("/api/" + path, headers=READ)
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        return response.get_json()

    def resolution(self, visit="v1", species="rat", outcome="capture_confirmed", **fields):
        return self.event("resolved-" + visit, "visit_resolved", "2026-01-02T15:00:00Z", visit_id=visit,
                          species_code=species, door_state="closed", outcome=outcome, **fields)

    def test_health_checks_existing_database_without_creating_one(self):
        self.assertEqual(self.client.get("/health").json, {"status": "ok"})
        client = create_app(dict(self.config, DB_PATH=self.root / "absent.sqlite3")).test_client()
        response = client.get("/health")
        self.assertEqual((response.status_code, response.json), (503, {"status": "unavailable"}))
        self.assertFalse((self.root / "absent.sqlite3").exists())
        self.cli("migrate")
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_migration_preserves_unrecognized_database(self):
        path = self.root / "existing.sqlite3"
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
            connection.execute("INSERT INTO unrelated VALUES (1)")
        connection.close()
        with self.assertRaisesRegex(RuntimeError, "existing database"):
            apply_migrations(path)
        with sqlite3.connect(path) as connection:
            self.assertEqual(connection.execute("SELECT id FROM unrelated").fetchone()[0], 1)
        connection.close()

    def test_roles_and_protocol_errors(self):
        event = self.event("t1", door_state="open")
        self.send(event, 401, {})
        self.send(event, 403, READ)
        self.send(event, 403, {"Authorization": "Bearer trap-2-key"})
        self.assertEqual(self.client.get("/api/traps", headers=WRITE).status_code, 403)
        self.assertEqual(self.client.post("/api/recommendations", headers=READ).status_code, 403)
        for data, content_type, status, code in (
            ('{"x":1,"x":2}', "application/json", 400, "invalid_json"),
            ("not json", "application/json", 400, "invalid_json"),
            ("{}", "text/plain", 415, "unsupported_media_type"),
            (" " * 70000, "application/json", 413, "request_entity_too_large"),
        ):
            response = self.client.post("/api/sensor/data", data=data, content_type=content_type, headers=DEVICE)
            self.assertEqual((response.status_code, response.json["error"]["code"]), (status, code))

    def test_normalized_retry_and_conflict_survive_restart(self):
        event = self.event("t1", env={"bait_g": 2})
        self.assertFalse(self.send(event)["duplicate"])
        self.client = create_app(self.config).test_client()
        retry = dict(event, observed_at="2026-01-02T23:59:00+09:00", env={"humidity_pct": None, "bait_g": 2.0})
        self.assertTrue(self.send(retry, 200)["duplicate"])
        self.assertEqual(self.send(dict(event, env={"bait_g": 3}), 409)["error"]["code"], "event_conflict")
        reading = self.read("readings")["items"][0]
        self.assertEqual(reading["env"]["bait_g"], 2)
        self.assertEqual(reading["observed_at"], "2026-01-02T14:59:00.000000Z")

    def test_concurrent_identical_event_is_inserted_once(self):
        payload = self.event("same-id", door_state="closed")

        def post(index):
            with self.app.test_client() as client:
                return client.post("/api/sensor/data", headers=DEVICE, json=payload).status_code

        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = sorted(pool.map(post, range(4)))
        self.assertEqual(statuses, [200, 200, 200, 201])

    def test_busy_write_returns_retryable_error(self):
        connection = connect(self.path)
        self.addCleanup(connection.close)
        connection.execute("BEGIN IMMEDIATE")
        try:
            with patch("app.db.BUSY_TIMEOUT_MS", 5):
                error = self.send(self.event("locked", door_state="open"), 503)
            self.assertEqual(error["error"]["code"], "database_busy")
        finally:
            connection.rollback()
        self.send(self.event("locked", door_state="open"))

    def test_validation_unknown_reference_and_unconfirmed_outcome(self):
        for fields in ({"humidity_pct": 101}, {"bait_g": -1}, {"temperature_c": True}, {"illuminance_lux": None}):
            self.send(self.event("invalid", env=fields), 400)
        self.send(self.event("invalid", observed_at="2026-01-02T14:59:00+08:70", door_state="open"), 400)
        self.send(dict(self.event("invalid", door_state="open"), deployment_id="missing"), 404)
        self.send(self.resolution(), 400)
        self.send(self.resolution(outcome="unconfirmed"))
        self.assertEqual(self.read("captures")["items"], [])

    def test_reversed_visit_and_conflicting_visit_times(self):
        self.send(self.resolution(outcome_evidence={"source": "test"}))
        before = self.read("visits?species_code=rat")["items"][0]
        self.assertIsNone(before["entry"])
        late_entry = self.event("late-entry", "entry_detected", "2026-01-02T15:01:00Z", visit_id="v1")
        self.send(late_entry, 409)
        entry = self.event("entry", "entry_detected", visit_id="v1", env={"humidity_pct": 50})
        self.send(entry)
        self.send(dict(entry, event_id="entry-second"), 409)
        after = self.read("visits?species_code=rat")["items"][0]
        self.assertEqual(after["entry"]["env"]["humidity_pct"], 50)
        self.assertEqual(after["resolution"]["outcome_evidence"], {"source": "test"})

    def test_relocation_keeps_old_events_separate_and_accepts_delay(self):
        self.send(self.event("old", env={"bait_g": 25}))
        self.cli("registry", "deploy", "earlier", "trap-1", "b", "rat", "2026-01-02T14:58:00Z", status=1)
        self.cli("registry", "deploy", "dep-2", "trap-1", "b", "rat", "2026-01-02T15:00:00Z")
        delayed = self.event("delayed", observed_at="2026-01-02T14:58:00Z", env={"bait_g": 12})
        self.send(delayed)
        self.send(dict(delayed, event_id="at-cutover", observed_at="2026-01-02T15:00:00Z"), 400)
        self.send(dict(delayed, event_id="new", deployment_id="dep-2", observed_at="2026-01-02T15:00:00Z"))
        self.client = create_app(self.config).test_client()
        state = self.read("traps/trap-1/status")
        self.assertEqual(state["deployment"]["location_id"], "b")
        self.assertEqual(state["observations"]["bait_g"]["value"], 12)
        page = self.read("readings?limit=1")
        self.assertEqual(page["next_offset"], 1)
        self.assertEqual(page["items"][0]["location_id"], "b")
        self.assertEqual([item["location_id"] for item in self.read("readings?offset=1")["items"]], ["a", "a"])

    def test_bait_thresholds_stale_and_ordered_fields(self):
        now = datetime.now(timezone.utc)
        old = utc_text(now - timedelta(minutes=10))
        self.send(self.event("old", observed_at=old, env={"bait_g": 0, "humidity_pct": 51}))
        self.assertEqual(self.read("traps/trap-1/status")["bait_status"], "unknown")
        for index, (weight, status) in enumerate(((2, "empty"), (10, "low"), (10.001, "ok"))):
            when = utc_text(now - timedelta(seconds=10 - index))
            self.send(self.event(f"bait-{index}", observed_at=when, env={"bait_g": weight}))
            self.assertEqual(self.read("traps/trap-1/status")["bait_status"], status)
        self.send(self.event("late", observed_at=old, env={"bait_g": 1}))
        state = self.read("traps/trap-1/status")
        self.assertEqual(state["bait_status"], "ok")
        self.assertEqual(state["connection_state"], "online")
        self.assertTrue(state["observations"]["humidity_pct"]["stale"])

    def test_daily_local_date_boundary_and_period(self):
        self.send(self.event("entry", "entry_detected", visit_id="v1"))
        self.send(self.resolution(outcome_evidence="occupancy-check"))
        self.send(self.resolution("v2", "mouse", outcome_evidence="manual-check"))
        self.send(self.event("pending", "entry_detected", visit_id="pending"))
        self.send(self.event("unknown-entry", "entry_detected", visit_id="unknown-visit"))
        self.send(self.resolution("unknown-visit", "unknown", "unconfirmed"))
        stats = self.read("stats/daily?" + TEST_PERIOD)
        self.assertEqual(stats["timezone"], "Asia/Seoul")
        entry, capture = stats["items"]
        self.assertEqual((entry["date"], entry["entries"], entry["target_entries"]), ("2026-01-02", 3, 1))
        self.assertEqual((entry["pending_entries"], entry["unclassified_entries"]), (1, 1))
        self.assertEqual((capture["date"], capture["confirmed_captures"], capture["non_target_captures"]),
                         ("2026-01-03", 2, 1))
        self.assertEqual(self.read("captures?to=2026-01-02T15:00:00Z")["items"], [])

    def test_csv_to_recommendation_round_trip(self):
        self.send(self.event("report", env={"bait_g": 12.5}))
        response = self.client.get("/api/export/events.csv?" + TEST_PERIOD, headers=READ, buffered=True)
        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
        self.assertEqual((rows[0]["event_id"], rows[0]["location_id"], rows[0]["bait_g"]), ("report", "a", "12.5"))
        self.read("export/events.csv?from=2026-01-01T00:00:00Z&to=2026-03-01T00:00:00Z", 400)
        self.assertEqual(len(self.read("locations")["items"]), 2)
        ready = dict(run_id="run-1", trap_id=rows[0]["trap_id"], target_species=rows[0]["target_species"],
                     model_version="mock-1", generated_at="2026-01-03T00:01:00Z", prediction_kind="target_entry",
                     data_from="2026-01-02T00:00:00Z", data_to="2026-01-03T00:00:00Z",
                     forecast_from="2026-01-03T01:00:00Z", forecast_to="2026-01-04T01:00:00Z",
                     status="ready", score_type="relative_score",
                     candidates=[dict(location_id="b", rank=1, score=0.8, reason="Mock score")])

        def submit(payload, expected):
            response = self.client.post("/api/recommendations", json=payload, headers=WRITE)
            self.assertEqual(response.status_code, expected, response.get_data(as_text=True))

        submit(dict(ready, candidates=[dict(ready["candidates"][0], location_id="missing")]), 404)
        submit(dict(ready, candidates=ready["candidates"] * 2), 400)
        self.assertEqual(self.read("recommendations")["items"], [])
        submit(ready, 201)
        submit(ready, 200)
        submit(dict(ready, model_version="other"), 409)
        latest_path = "recommendations/latest?trap_id=trap-1&target_species=rat&prediction_kind=target_entry"
        self.assertEqual(self.read(latest_path)["candidates"], ready["candidates"])
        insufficient = dict(ready, run_id="run-2", status="insufficient_data", generated_at="2026-01-03T00:02:00Z",
                            score_type=None, candidates=[], reason="No observation coverage")
        submit(insufficient, 201)
        self.assertEqual(self.read(latest_path)["status"], "insufficient_data")
        history = self.read("recommendations?limit=1")
        self.assertEqual((history["items"][0]["run_id"], history["next_offset"]), ("run-2", 1))

    def test_read_auth_can_be_turned_off_without_opening_writes(self):
        client = create_app(dict(self.config, READ_AUTH="off")).test_client()
        self.assertEqual(client.get("/api/traps").status_code, 200)
        self.assertEqual(client.get("/api/deployments").status_code, 200)
        self.assertEqual(client.post("/api/sensor/data", json=self.event("t1")).status_code, 401)
        self.assertEqual(client.post("/api/recommendations", json={}).status_code, 401)
        self.assertEqual(self.client.get("/api/traps").status_code, 401)
        with self.assertRaisesRegex(RuntimeError, "TRAP_READ_AUTH"):
            create_app(dict(self.config, READ_AUTH="maybe"))

    def test_deployment_history_includes_relocation(self):
        self.cli("registry", "deploy", "dep-2", "trap-1", "b", "rat", "2026-01-05T00:00:00Z")
        items = self.read("deployments?trap_id=trap-1")["items"]
        self.assertEqual([(d["deployment_id"], d["location_id"]) for d in items], [("dep-1", "a"), ("dep-2", "b")])
        self.assertEqual((items[0]["ended_at"], items[1]["ended_at"]), ("2026-01-05T00:00:00.000000Z", None))
        self.read("deployments?trap_id=missing", 404)

    def test_recommendation_keeps_data_basis_and_details(self):
        run = dict(run_id="run-basis", trap_id="trap-1", target_species="rat", model_version="score-v0.1",
                   generated_at="2026-01-03T00:01:00Z", prediction_kind="target_entry",
                   data_from="2026-01-02T00:00:00Z", data_to="2026-01-03T00:00:00Z",
                   forecast_from="2026-01-03T01:00:00Z", forecast_to="2026-01-04T01:00:00Z",
                   status="ready", score_type="relative_score",
                   candidates=[dict(location_id="b", rank=1, score=0.8, reason="PC 분석")],
                   data_basis=dict(detection_data="actual", capture_data="synthetic", is_simulation_based=True,
                                   note="포획 수치는 가상 데이터 기반"),
                   details=dict(decision="recommended", simulated_stats=dict(captures=6)))

        def submit(payload, expected):
            response = self.client.post("/api/recommendations", json=payload, headers=WRITE)
            self.assertEqual(response.status_code, expected, response.get_data(as_text=True))

        submit(dict(run, data_basis=dict(run["data_basis"], is_simulation_based="yes")), 400)
        submit(dict(run, data_basis=dict(run["data_basis"], capture_data="real")), 400)
        submit(dict(run, data_basis={"note": "x"}), 400)
        submit(dict(run, details=[1]), 400)
        submit(run, 201)
        stored = self.read("recommendations/latest?trap_id=trap-1")
        self.assertEqual((stored["data_basis"], stored["details"]), (run["data_basis"], run["details"]))

    def test_dashboard_build_and_api_coexist(self):
        build = self.root / "dist"
        (build / "assets").mkdir(parents=True)
        (build / "index.html").write_text("<h1>Dashboard</h1>", encoding="utf-8")
        (build / "assets" / "ui.css").write_text("body { color: black; }", encoding="utf-8")
        client = create_app(dict(self.config, DASHBOARD_DIR=build)).test_client()
        with client.get("/") as response:
            self.assertIn(b"Dashboard", response.data)
        with client.get("/assets/ui.css") as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get("/api/traps", headers=READ).status_code, 200)
        self.assertEqual(client.get("/api/missing").json["error"]["code"], "not_found")

    def test_csv_closes_database_on_head_or_partial_download(self):
        self.send(self.event("report", env={"bait_g": 12.5}))
        connections = []

        def track_connection(path):
            connection = connect(path)
            connections.append(connection)
            return connection

        with patch("app.db.connect", side_effect=track_connection):
            for method in ("HEAD", "GET"):
                with self.subTest(method=method):
                    with self.client.open("/api/export/events.csv?" + TEST_PERIOD, method=method,
                                          headers=READ, buffered=False) as response:
                        self.assertEqual(response.status_code, 200)
                        if method == "GET":
                            self.assertTrue(next(iter(response.response)).startswith(b"schema_version,"))
                    with self.assertRaises(sqlite3.ProgrammingError):
                        connections[-1].execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
