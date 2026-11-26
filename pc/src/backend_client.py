"""Pi 백엔드(backend/docs/api.md) 연동.

PC 쪽 추천 결과(payload: 한 번의 실행에 모든 트랩)를 백엔드 형식(트랩 하나가 run 하나)으로 바꿔 보내고,
다시 읽을 때 원래 형식으로 되돌린다. 백엔드에 칸이 없는 PC 전용 값은 run의 `data_basis`와 `details`에 담는다.

- 이 변환은 정보를 잃지 않는다. 가상 포획 표시(data_basis)와 실제/가상 통계 분리(actual_stats, simulated_stats)도 그대로 남는다.
- 백엔드의 status는 ready/insufficient_data뿐이다. PC의 판정은 details.decision에 둔다.
  recommended -> ready(후보: 추천 위치 1순위, 현재 위치 2순위), keep -> ready(후보: 현재 위치),
  device_check, insufficient_data -> insufficient_data(후보 없음, 사유는 reason).
- 이 클라이언트는 추천 결과 저장·조회와 health만 지원한다. 센서·감지 이력 읽기는 CSV 내보내기를 쓸 때 추가한다.
"""
from datetime import datetime, timedelta

import requests

from src.api_client import ApiClient, ApiError

FORECAST_HOURS = 24
MAX_RUNS = 500  # 한 번에 읽는 run 수(백엔드 limit 최대값)
DECISIONS = {"recommended", "keep", "device_check", "insufficient_data"}


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _candidates(item):
    status, current = item["status"], item["current_location_id"]
    reason = item["reasons"][0]
    if status == "recommended":
        found = [{"location_id": item["recommended_location_id"], "rank": 1, "score": item["score"], "reason": reason}]
        if item["current_location_score"] is not None and current != item["recommended_location_id"]:
            found.append({"location_id": current, "rank": 2, "score": item["current_location_score"],
                          "reason": "현재 위치"})
        return found
    if status == "keep":
        if item["current_location_score"] is None:
            raise ValueError(f"{item['trap_id']}: keep인데 현재 위치 점수가 없음")
        return [{"location_id": current, "rank": 1, "score": item["current_location_score"], "reason": reason}]
    return []


def to_backend_runs(payload, target_species="rat", forecast_hours=FORECAST_HOURS):
    """추천 payload를 트랩별 백엔드 run 목록으로 바꾼다."""
    generated = datetime.fromisoformat(payload["generated_at"])
    period = payload["analysis_period"]
    runs = []
    for index, item in enumerate(payload["recommendations"]):
        if item["status"] not in DECISIONS:
            raise ValueError(f"{item['trap_id']}: 알 수 없는 status {item['status']!r}")
        candidates = _candidates(item)
        run = {
            "run_id": f"{payload['run_id']}-{item['trap_id']}", "trap_id": item["trap_id"],
            "target_species": target_species, "model_version": payload["algorithm_version"],
            "generated_at": payload["generated_at"], "prediction_kind": "target_entry",
            "data_from": period["from"], "data_to": period["to"],
            "forecast_from": payload["generated_at"], "forecast_to": _iso(generated + timedelta(hours=forecast_hours)),
            "status": "ready" if candidates else "insufficient_data",
            "candidates": candidates, "data_basis": payload["data_basis"],
            "details": {
                "batch_id": payload["run_id"], "index": index, "decision": item["status"],
                "relocate": item["relocate"], "priority": item["priority"],
                "recommended_location_type": item["recommended_location_type"],
                "current_location_id": item["current_location_id"],
                "current_location_score": item["current_location_score"], "reasons": item["reasons"],
                "actual_stats": item["actual_stats"], "simulated_stats": item["simulated_stats"],
            },
        }
        if candidates:
            run["score_type"] = "relative_score"
        else:
            run["reason"] = " ".join(item["reasons"])
        runs.append(run)
    return runs


def from_backend_runs(runs):
    """같은 실행(batch)의 백엔드 run들을 PC 추천 형식으로 되돌린다. PC가 보낸 run(details.decision)만 대상이다."""
    runs = sorted((r for r in runs if (r.get("details") or {}).get("decision") in DECISIONS),
                  key=lambda r: r["details"]["index"])
    if not runs:
        return None
    items = []
    for run in runs:
        d, decision = run["details"], run["details"]["decision"]
        top = run["candidates"][0] if decision == "recommended" else None
        items.append({
            "trap_id": run["trap_id"], "current_location_id": d["current_location_id"],
            "recommended_location_id": top["location_id"] if top else None,
            "recommended_location_type": d["recommended_location_type"], "relocate": d["relocate"],
            "status": decision, "priority": d["priority"], "score": top["score"] if top else None,
            "current_location_score": d["current_location_score"], "reasons": d["reasons"],
            "actual_stats": d["actual_stats"], "simulated_stats": d["simulated_stats"],
        })
    first = runs[0]
    return {"run_id": first["details"]["batch_id"], "generated_at": first["generated_at"],
            "analysis_period": {"from": first["data_from"], "to": first["data_to"]},
            "algorithm_version": first["model_version"], "data_basis": first["data_basis"],
            "recommendations": items}


class BackendTransport:
    """ApiClient가 쓰는 전송 계층의 백엔드 구현. base_url은 서버 주소(예: http://<Pi>:5000), /api 경로는 내부에서 붙인다."""

    def __init__(self, base_url, read_token=None, write_token=None, timeout=10, session=None):
        self.base_url = base_url.rstrip("/")
        self.read_token, self.write_token = read_token, write_token
        self.timeout = timeout
        self.session = session or requests

    @staticmethod
    def _error(status, code, message):
        return status, {"error": {"code": code, "message": message, "details": {}}}

    def _http(self, method, path, params=None, body=None, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            r = self.session.request(method, self.base_url + path, params=params, json=body,
                                     headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise ApiError(0, "CONNECTION_ERROR", str(e)) from e
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, None

    def request(self, method, path, params=None, body=None):
        if path == "/health" and method == "GET":
            return self._http("GET", "/health")
        if path == "/recommendations":
            return self._post_runs(body) if method == "POST" else self._get_runs(params or {})
        return self._error(501, "NOT_IMPLEMENTED", f"{method} {path}: 백엔드 연동에서 아직 지원하지 않음")

    def _post_runs(self, body):
        saved = 0
        for run in to_backend_runs(body):
            status, payload = self._http("POST", "/api/recommendations", body=run, token=self.write_token)
            if status >= 400 or not isinstance(payload, dict):
                if saved and isinstance(payload, dict) and "error" in payload:
                    payload["error"]["message"] += f" (앞선 {saved}건은 이미 저장됨)"
                return status, payload
            if payload.get("duplicate"):  # 백엔드는 같은 내용 재전송을 200으로 받지만, PC는 같은 run_id 재전송을 거절한다
                return self._error(409, "DUPLICATE_RESOURCE", f"run_id exists: {body['run_id']}")
            saved += 1
        return 201, {"run_id": body["run_id"], "saved_count": saved, "saved_at": body["generated_at"]}

    def _get_runs(self, params):
        status, payload = self._http("GET", "/api/recommendations", {"limit": MAX_RUNS}, token=self.read_token)
        if status >= 400 or not isinstance(payload, dict):
            return status, payload
        mine = [r for r in payload["items"] if (r.get("details") or {}).get("batch_id")]
        batch = params.get("run_id") or (mine[0]["details"]["batch_id"] if mine else None)
        result = from_backend_runs([r for r in mine if r["details"]["batch_id"] == batch])
        if result is None:
            return self._error(404, "NOT_FOUND", "no recommendation run")
        return 200, result


def backend_client(base_url, **kwargs):
    """실제 백엔드용 ApiClient. 예: backend_client("http://<Pi>:5000", read_token=..., write_token=...)"""
    return ApiClient(BackendTransport(base_url, **kwargs))
