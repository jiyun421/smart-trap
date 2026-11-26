# smart-trap

AI 스마트 트랩 프로젝트 (ESP32, Arduino Nano 33 BLE Sense Lite, Raspberry Pi 5, PC).

## 폴더 구조

| 폴더       | 내용                                                                                     | 담당   |
| ---------- | ---------------------------------------------------------------------------------------- | ------ |
| `backend/` | Raspberry Pi 백엔드 (Flask, Gunicorn, SQLite). ESP32 수신, 조회·집계 API, 추천 결과 저장 | 백엔드 |
| `pc/`      | 데이터 분석, 위치 추천 알고리즘, 웹 대시보드, 목업 서버                                  | PC     |
| `docs/`    | 팀 공통 문서 (API 명세 초안 등). 실제 구현 기준 API는 `backend/docs/api.md`              | 공통   |

각 폴더의 실행 방법은 해당 폴더의 `README.md`를 봅니다.

- 백엔드: [backend/README.md](backend/README.md)
- PC: [pc/README.md](pc/README.md)

## 작업 규칙

- 각 폴더는 독립된 Python 환경을 씁니다. 백엔드는 Python 3.11 이상이고 `backend/.venv`, PC는 `pc/.venv`를 권장합니다.
- 다른 담당 폴더의 코드는 직접 고치지 않고 이슈나 PR로 요청합니다.
- `.env`, 토큰, DB 파일은 커밋하지 않습니다.
