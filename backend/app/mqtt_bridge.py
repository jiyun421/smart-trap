"""ESP32의 MQTT 이벤트를 POST /api/sensor/data로 옮기는 중계. 실행: python -m app.mqtt_bridge

observed_at은 중계가 받은 시각이다(보드에는 시계가 없다). 서버에 닿지 않으면 받은 순서대로 들고 재시도한다.
들고 있는 이벤트는 메모리에만 있어, 중계를 다시 시작하면 사라진다.
"""

import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .validation import utc_text

log = logging.getLogger(__name__)

TOPIC = "trap/v1/+/event"
ENV_NAMES = {"temp_c": "temperature_c", "humidity_pct": "humidity_pct", "lux": "illuminance_lux",
             "load_g": "bait_g", "eco2": "eco2_ppm", "tvoc": "tvoc_ppb"}
SPECIES = {"target": "rat", "other": "non_rat", "fail": "unknown"}
RESULTS = (*SPECIES, "empty", "periodic")
DOORS = {"open": "open", "closed": "closed", "between": "unknown"}
# 펌웨어는 같은 기록을 60초 간격으로 다시 보낸다. 이 시간 안의 같은 (boot, uptimeMs)는 한 번만 저장한다.
DUPLICATE_SECONDS = 600
RETRY_SECONDS = 5


def convert(message, received_at):
    """펌웨어 메시지 하나를 API 이벤트로 바꾼다. deployment_id는 전송할 때 채운다."""
    result = message.get("result")
    door = message.get("door")
    boot, uptime = message.get("boot"), message.get("uptimeMs")
    if result not in RESULTS or door not in DOORS or type(boot) is not int or type(uptime) is not int:
        raise ValueError("result, door, boot or uptimeMs is missing or unsupported")

    env = {name: message[key] for key, name in ENV_NAMES.items() if message.get(key) is not None}
    # 보정 오차로 음수가 된 무게는 서버가 이벤트 전체를 거절하므로 뺀다.
    if isinstance(env.get("bait_g"), (int, float)) and env["bait_g"] < 0:
        del env["bait_g"]

    # 전원이 끊기면 boot가 처음부터 다시 세므로 수신 시각을 ID에 넣는다.
    key = f"esp-{boot}-{uptime}-{received_at:%Y%m%dT%H%M%S%fZ}"
    common = {"schema_version": 1, "trap_id": message.get("trapId"), "observed_at": utc_text(received_at)}
    if result not in SPECIES:
        event = dict(common, event_id=key, event_type="telemetry", door_state=DOORS[door])
        if env:
            event["env"] = env
        if result == "empty":
            event["occupancy_state"] = "empty"
        return [event]

    entry = dict(common, event_id=key + "-entry", event_type="entry_detected", visit_id=key)
    if env:
        entry["env"] = env
    resolved = dict(common, event_id=key + "-resolved", event_type="visit_resolved", visit_id=key,
                    species_code=SPECIES[result], door_state=DOORS[door], outcome="unconfirmed")
    return [entry, resolved]


class Bridge:
    def __init__(self, api_url, device_tokens, read_token="", sleep=time.sleep, timeout=10):
        self.api_url = api_url.rstrip("/")
        self.device_tokens = device_tokens
        self.read_token = read_token
        self.sleep = sleep
        self.timeout = timeout
        self.seen = {}

    def receive(self, topic, payload):
        """저장할 이벤트 목록을 돌려준다. 쓸 수 없거나 이미 받은 메시지면 None."""
        try:
            message = json.loads(payload.decode("utf-8"))
            if not isinstance(message, dict):
                raise ValueError("not a JSON object")
            trap_id = message.get("trapId")
            if topic != f"trap/v1/{trap_id}/event" or trap_id not in self.device_tokens:
                raise ValueError("trapId does not match the topic or has no device token")
            events = convert(message, datetime.now(timezone.utc))
        except ValueError as error:
            log.warning("Ignored message on %s: %s", topic, error)
            return None

        now = time.monotonic()
        self.seen = {key: when for key, when in self.seen.items() if now - when < DUPLICATE_SECONDS}
        key = (trap_id, message["boot"], message["uptimeMs"], message["result"])
        if key in self.seen:
            log.info("Ignored resent message: boot=%s uptimeMs=%s", key[1], key[2])
            return None
        self.seen[key] = now
        log.info("Received %s from %s (boot=%s)", message["result"], trap_id, message["boot"])
        return events

    def deliver(self, events):
        """저장될 때까지 재시도한다. 서버가 거절한(4xx) 이벤트는 기록하고 버린다."""
        trap_id = events[0]["trap_id"]
        while True:
            try:
                deployment_id = self.active_deployment(trap_id)
                if deployment_id is None:
                    log.error("Dropped: %s has no active deployment", trap_id)
                    return
                for event in events:
                    event.setdefault("deployment_id", deployment_id)
                    self.request("/api/sensor/data", self.device_tokens[trap_id], event)
                return
            except urllib.error.HTTPError as error:
                if error.code < 500:
                    log.error("Dropped %s: HTTP %s %s", events[0]["event_id"], error.code,
                              error.read().decode("utf-8", "replace"))
                    return
                log.warning("Server error %s, retrying", error.code)
            except OSError as error:
                log.warning("Server unreachable, retrying: %s", error)
            self.sleep(RETRY_SECONDS)

    def active_deployment(self, trap_id):
        traps = self.request("/api/traps", self.read_token)["items"]
        return next((trap["deployment_id"] for trap in traps if trap["trap_id"] == trap_id), None)

    def request(self, path, token, body=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.api_url + path, data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)


def main():
    import paho.mqtt.client as mqtt

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    bridge = Bridge(
        os.environ.get("TRAP_API_URL", "http://127.0.0.1:5000"),
        json.loads(os.environ.get("TRAP_DEVICE_TOKENS", "{}")),
        os.environ.get("TRAP_READ_TOKEN", ""),
    )
    if not bridge.device_tokens:
        raise SystemExit("TRAP_DEVICE_TOKENS is empty")
    jobs = queue.Queue()

    def work():
        while True:
            events = jobs.get()
            try:
                bridge.deliver(events)
            except Exception:
                log.exception("Dropped %s", events[0]["event_id"])

    def on_connect(client, userdata, flags, reason_code, properties):
        log.info("MQTT connected: %s", reason_code)
        client.subscribe(TOPIC)

    def on_message(client, userdata, received):
        events = bridge.receive(received.topic, received.payload)
        if events:
            jobs.put(events)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    threading.Thread(target=work, daemon=True).start()
    client.connect_async(os.environ.get("TRAP_MQTT_HOST", "127.0.0.1"), int(os.environ.get("TRAP_MQTT_PORT", "1883")))
    client.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
