import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.serving import WSGIRequestHandler, make_server

from app import create_app
from app.mqtt_bridge import Bridge, convert

TOPIC = "trap/v1/TRAP-01/event"
# 펌웨어 04_NOTICE.md의 예시 메시지
MESSAGE = {
    "trapId": "TRAP-01", "location": "z-kitchen", "boot": 12, "uptimeMs": 8450, "result": "target", "species": 1,
    "command": "hold", "door": "closed", "load_g": 52.3, "temp_c": 23.1, "humidity_pct": 55.2, "lux": 130.0,
    "battery_mv": None, "eco2": 450, "tvoc": 12,
}
ENV = {"temperature_c": 23.1, "humidity_pct": 55.2, "illuminance_lux": 130.0, "bait_g": 52.3,
       "eco2_ppm": 450, "tvoc_ppb": 12}
NOW = datetime(2026, 11, 27, 3, 4, 5, 6, tzinfo=timezone.utc)


def message(**changes):
    return dict(MESSAGE, **changes)


class ConvertTest(unittest.TestCase):
    def test_visit_results_become_entry_and_resolution(self):
        for result, species in (("target", "rat"), ("other", "non_rat"), ("fail", "unknown")):
            with self.subTest(result=result):
                entry, resolved = convert(message(result=result), NOW)
                self.assertEqual((entry["event_type"], resolved["event_type"]), ("entry_detected", "visit_resolved"))
                self.assertEqual(entry["visit_id"], resolved["visit_id"])
                self.assertNotEqual(entry["event_id"], resolved["event_id"])
                self.assertEqual(entry["env"], ENV)
                self.assertNotIn("env", resolved)
                self.assertNotIn("door_state", entry)
                self.assertEqual((resolved["species_code"], resolved["door_state"], resolved["outcome"]),
                                 (species, "closed", "unconfirmed"))
                self.assertEqual(entry["observed_at"], "2026-11-27T03:04:05.000006Z")

    def test_empty_and_periodic_become_telemetry(self):
        (empty,) = convert(message(result="empty", door="open"), NOW)
        self.assertEqual((empty["event_type"], empty["occupancy_state"], empty["door_state"]),
                         ("telemetry", "empty", "open"))
        (periodic,) = convert(message(result="periodic", door="between"), NOW)
        self.assertEqual((periodic["event_type"], periodic["door_state"]), ("telemetry", "unknown"))
        self.assertNotIn("occupancy_state", periodic)
        self.assertNotIn("visit_id", periodic)

    def test_missing_and_negative_readings_are_left_out(self):
        (event,) = convert(message(result="periodic", load_g=-3.2, temp_c=None, eco2=None, tvoc=None), NOW)
        self.assertEqual(event["env"], {"humidity_pct": 55.2, "illuminance_lux": 130.0})

    def test_restarted_boot_counter_does_not_reuse_ids(self):
        later = NOW.replace(hour=9)
        self.assertNotEqual(convert(MESSAGE, NOW)[0]["event_id"], convert(MESSAGE, later)[0]["event_id"])


class QuietHandler(WSGIRequestHandler):
    def log(self, *args):
        pass


class BridgeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.app = create_app({
            "TESTING": True, "DB_PATH": Path(temporary.name) / "test.sqlite3", "DASHBOARD_DIR": None,
            "DEVICE_TOKENS": {"TRAP-01": "device-key"}, "READ_TOKEN": "pc-read", "READ_AUTH": "required",
            "RECOMMENDATION_TOKEN": "pc-write",
        })
        for args in (
            ("migrate",),
            ("registry", "trap", "TRAP-01", "Trap", "--empty-g", "2", "--low-g", "10", "--interval", "700"),
            ("registry", "location", "z-kitchen", "Kitchen"),
            ("registry", "deploy", "dep-1", "TRAP-01", "z-kitchen", "rat", "2026-01-01T00:00:00Z"),
        ):
            result = self.app.test_cli_runner().invoke(args=list(args))
            self.assertEqual(result.exit_code, 0, result.output)
        self.server = make_server("127.0.0.1", 0, self.app, request_handler=QuietHandler)
        self.addCleanup(self.server.server_close)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.sleeps = []

    def serve(self):
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def bridge(self, **changes):
        options = dict(api_url=self.url, device_tokens={"TRAP-01": "device-key"}, read_token="pc-read",
                       sleep=self.sleeps.append, timeout=1)
        return Bridge(**dict(options, **changes))

    def receive(self, bridge, topic=TOPIC, **changes):
        return bridge.receive(topic, json.dumps(message(**changes)).encode())

    def read(self, path):
        response = self.app.test_client().get("/api/" + path, headers={"Authorization": "Bearer pc-read"})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_visit_message_is_stored(self):
        self.serve()
        bridge = self.bridge()
        bridge.deliver(self.receive(bridge))
        (visit,) = self.read("visits")["items"]
        self.assertEqual((visit["location_id"], visit["species_code"]), ("z-kitchen", "rat"))
        self.assertEqual(visit["entry"]["env"], ENV)
        self.assertEqual(visit["resolution"]["outcome"], "unconfirmed")
        status = self.read("traps/TRAP-01/status")
        self.assertEqual(status["observations"]["door_state"]["value"], "closed")
        self.assertEqual(status["connection_state"], "online")
        self.assertEqual(self.sleeps, [])

    def test_firmware_resend_is_ignored(self):
        bridge = self.bridge()
        self.assertIsNotNone(self.receive(bridge))
        self.assertIsNone(self.receive(bridge))
        self.assertIsNotNone(self.receive(bridge, boot=13))

    def test_unusable_messages_are_ignored(self):
        bridge = self.bridge()
        with self.assertLogs("app.mqtt_bridge", "WARNING"):
            for payload in (b"not json", b"[1]", b"\xff", b"{}"):
                self.assertIsNone(bridge.receive(TOPIC, payload))
            self.assertIsNone(self.receive(bridge, result="rat"))
            self.assertIsNone(self.receive(bridge, boot="12"))
            self.assertIsNone(self.receive(bridge, door=3))
            self.assertIsNone(self.receive(bridge, topic="trap/v1/TRAP-02/event"))
            self.assertIsNone(self.receive(bridge, topic="trap/v1/TRAP-02/event", trapId="TRAP-02"))

    def test_waits_for_the_server_to_come_back(self):
        # 포트는 열려 있지만 응답하지 않는 서버: 두 번 실패한 뒤 서버를 켠다.
        def sleep(seconds):
            self.sleeps.append(seconds)
            if len(self.sleeps) == 2:
                self.serve()

        bridge = self.bridge(sleep=sleep, timeout=0.2)
        with self.assertLogs("app.mqtt_bridge", "WARNING"):
            bridge.deliver(self.receive(bridge))
        self.assertEqual(len(self.sleeps), 2)
        self.assertEqual(len(self.read("visits")["items"]), 1)

    def test_rejected_message_is_dropped_without_retry(self):
        self.serve()
        bridge = self.bridge(device_tokens={"TRAP-01": "wrong-key"})
        with self.assertLogs("app.mqtt_bridge", "ERROR"):
            bridge.deliver(self.receive(bridge))
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.read("visits")["items"], [])


if __name__ == "__main__":
    unittest.main()
