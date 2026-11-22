"""Raspberry Pi API 클라이언트 (API 명세 v1.0).

두 가지 방식으로 같은 인터페이스를 쓴다.
- ApiClient.from_mock(): data/mock/*.json 으로 동작 (서버 없이 개발/테스트)
- ApiClient.from_url("http://<RPI_IP>:<PORT>/api/v1"): 실제 서버 호출

실제 서버 연동은 Pi 담당자가 명세 구현을 확인한 뒤에만 사용한다.
"""
import json
from datetime import datetime
from pathlib import Path

import requests

MOCK_DIR = Path(__file__).resolve().parent.parent / "data" / "mock"
MAX_PAGE_SIZE = 1000


class ApiError(Exception):
    """API 오류 응답 ({"error": {"code", "message", "details"}})."""

    def __init__(self, status, code, message, details=None):
        super().__init__(f"[{status}] {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


# ---------------------------------------------------------------- 전송 계층
class HttpTransport:
    def __init__(self, base_url, timeout=10, api_key=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {"X-API-Key": api_key} if api_key else {}

    def request(self, method, path, params=None, body=None):
        try:
            r = requests.request(method, self.base_url + path, params=params, json=body,
                                 headers=self.headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise ApiError(0, "CONNECTION_ERROR", str(e)) from e
        try:
            payload = r.json()
        except ValueError:
            payload = None
        return r.status_code, payload


class MockTransport:
    """data/mock/*.json 을 서버처럼 응답한다. 필터와 페이지네이션도 명세대로 흉내 낸다."""

    # path -> (파일명, 시각 필드). 시각 필드가 None이면 기간 필터 없음
    PAGED = {
        "/sensor-readings": ("sensor_readings.json", "measured_at"),
        "/detection-events": ("detection_events.json", "detected_at"),
        "/trap-status-logs": ("trap_status_logs.json", "changed_at"),
    }
    SIMPLE = {
        "/health": "health.json",
        "/traps": "traps.json",
        "/locations": "locations.json",
        "/trap-location-history": "trap_location_history.json",
    }

    def __init__(self, mock_dir=MOCK_DIR):
        self.dir = Path(mock_dir)
        self.saved_runs = {}  # POST /recommendations 로 저장된 결과 (메모리)

    def _load(self, name):
        return json.loads((self.dir / name).read_text(encoding="utf-8"))

    @staticmethod
    def _err(status, code, message):
        return status, {"error": {"code": code, "message": message, "details": {}}}

    def request(self, method, path, params=None, body=None):
        params = params or {}
        if path == "/recommendations":
            return self._recommendations(method, params, body)
        if method != "GET":
            return self._err(404, "NOT_FOUND", path)
        if path in self.SIMPLE:
            data = self._load(self.SIMPLE[path])
            if path == "/trap-location-history" and "trap_id" in params:
                data = {"data": [r for r in data["data"] if r["trap_id"] == params["trap_id"]]}
            return 200, data
        if path in self.PAGED:
            return self._paged(*self.PAGED[path], params)
        return self._err(404, "NOT_FOUND", path)

    def _paged(self, filename, ts_field, p):
        page, size = int(p.get("page", 1)), int(p.get("page_size", 100))
        if page < 1 or not 1 <= size <= MAX_PAGE_SIZE:
            return self._err(400, "INVALID_PARAMETER", "page/page_size out of range")
        frm, to = p.get("from"), p.get("to")
        if frm and to and datetime.fromisoformat(frm) >= datetime.fromisoformat(to):
            return self._err(400, "INVALID_PARAMETER", "from must be earlier than to")
        rows = self._load(filename)["data"]
        if "trap_id" in p:
            rows = [r for r in rows if r["trap_id"] == p["trap_id"]]
        if frm:
            rows = [r for r in rows if datetime.fromisoformat(r[ts_field]) >= datetime.fromisoformat(frm)]
        if to:
            rows = [r for r in rows if datetime.fromisoformat(r[ts_field]) < datetime.fromisoformat(to)]
        chunk = rows[(page - 1) * size: page * size]
        meta = {"page": page, "page_size": size, "total": len(rows), "from": frm, "to": to}
        return 200, {"data": chunk, "meta": meta}

    REQUIRED = ("run_id", "generated_at", "analysis_period", "algorithm_version",
                "data_basis", "recommendations")

    def _recommendations(self, method, params, body):
        if method == "POST":
            missing = [k for k in self.REQUIRED if not isinstance(body, dict) or k not in body]
            if missing:
                return self._err(422, "VALIDATION_FAILED", f"missing fields: {missing}")
            if body["run_id"] in self.saved_runs:
                return self._err(409, "DUPLICATE_RESOURCE", f"run_id exists: {body['run_id']}")
            self.saved_runs[body["run_id"]] = {**body, "saved_at": body["generated_at"]}
            return 201, {"run_id": body["run_id"], "saved_count": len(body["recommendations"]),
                         "saved_at": body["generated_at"]}
        if "run_id" in params:
            run = self.saved_runs.get(params["run_id"])
        else:
            run = list(self.saved_runs.values())[-1] if self.saved_runs else None
        if run is None:
            return self._err(404, "NOT_FOUND", "no recommendation run")
        return 200, run


# -------------------------------------------------------------- 클라이언트
class ApiClient:
    def __init__(self, transport):
        self._t = transport

    @classmethod
    def from_mock(cls, mock_dir=MOCK_DIR):
        return cls(MockTransport(mock_dir))

    @classmethod
    def from_url(cls, base_url, **kwargs):
        return cls(HttpTransport(base_url, **kwargs))

    def _call(self, method, path, params=None, body=None):
        status, payload = self._t.request(method, path, params, body)
        if status >= 400 or not isinstance(payload, (dict, list)):
            err = payload.get("error", {}) if isinstance(payload, dict) else {}
            raise ApiError(status, err.get("code", "UNKNOWN_ERROR"),
                           err.get("message", "unexpected response"), err.get("details"))
        return payload

    def _get_all(self, path, from_, to, trap_id=None, page_size=MAX_PAGE_SIZE):
        """모든 페이지를 순서대로 받아 하나의 리스트로 합친다."""
        rows, page = [], 1
        while True:
            params = {"from": from_, "to": to, "page": page, "page_size": page_size}
            if trap_id:
                params["trap_id"] = trap_id
            body = self._call("GET", path, params)
            rows.extend(body["data"])
            if len(rows) >= body["meta"]["total"] or not body["data"]:
                return rows
            page += 1

    # --- 조회 (GET)
    def health(self):
        return self._call("GET", "/health")

    def get_traps(self):
        return self._call("GET", "/traps")["data"]

    def get_locations(self):
        return self._call("GET", "/locations")["data"]

    def get_location_history(self, trap_id=None):
        params = {"trap_id": trap_id} if trap_id else None
        return self._call("GET", "/trap-location-history", params)["data"]

    def get_sensor_readings(self, from_, to, trap_id=None):
        return self._get_all("/sensor-readings", from_, to, trap_id)

    def get_detection_events(self, from_, to, trap_id=None):
        return self._get_all("/detection-events", from_, to, trap_id)

    def get_status_logs(self, from_, to, trap_id=None):
        return self._get_all("/trap-status-logs", from_, to, trap_id)

    # --- 추천 결과
    def post_recommendations(self, payload):
        return self._call("POST", "/recommendations", body=payload)

    def get_recommendations(self, run_id=None):
        params = {"run_id": run_id} if run_id else {"latest": "true"}
        return self._call("GET", "/recommendations", params)
