"""개발용 로컬 Mock 서버 (실제 Pi 서버가 아님).

- /api/v1/* 는 MockTransport가 명세대로 응답한다 → HttpTransport/ApiClient.from_url, 대시보드 apiBase를 네트워크 경로로 검증.
- 그 밖의 경로는 프로젝트 폴더의 정적 파일(대시보드 포함)을 제공한다 → 대시보드가 Pi에서 제공될 때와 같은 출처(same-origin) 구조.
실행: python -m src.mock_server [포트]   (기본 8000, 127.0.0.1에만 바인딩)
"""
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from src.api_client import MockTransport

ROOT = str(Path(__file__).resolve().parent.parent)  # 경로 구분자(\ 또는 /)와 무관하게 프로젝트 루트(pc/)
PREFIX = "/api/v1"


class Handler(SimpleHTTPRequestHandler):
    transport = None  # make_server가 서버마다 주입

    def _api(self, method):
        u = urlsplit(self.path)
        body = None
        if method == "POST":
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                body = json.loads(raw)
            except ValueError:
                return self._send(400, {"error": {"code": "INVALID_PARAMETER", "message": "invalid JSON", "details": {}}})
        status, payload = self.transport.request(method, u.path[len(PREFIX):], dict(parse_qsl(u.query)), body)
        self._send(status, payload)

    def _send(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith(PREFIX + "/"):
            return self._api("GET")
        super().do_GET()

    def do_POST(self):
        if self.path.startswith(PREFIX + "/"):
            return self._api("POST")
        self.send_error(404)

    def log_message(self, *args):
        pass


def make_server(port=0, mock_dir=None):
    """port=0이면 빈 포트를 고른다. 서버마다 새 MockTransport(저장된 run 초기화)를 쓴다."""
    transport = MockTransport(mock_dir) if mock_dir else MockTransport()
    handler = type("BoundHandler", (Handler,), {"transport": transport})
    return ThreadingHTTPServer(("127.0.0.1", port), partial(handler, directory=ROOT))


def start_in_thread(port=0, mock_dir=None):
    server = make_server(port, mock_dir)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    srv = make_server(port)
    print(f"Mock 서버: http://127.0.0.1:{port}/dashboard/  (API: {PREFIX}, Ctrl+C로 종료)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
