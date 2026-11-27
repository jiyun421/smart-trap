# AI 트랩도어 Raspberry Pi 백엔드

Raspberry Pi 5에서 Flask, Gunicorn, SQLite를 실행합니다. ESP32가 보낸 환경·방문 관측을 저장하고, PC 분석 프로그램과 대시보드에 상태, 이력, 통계, CSV 및 위치 추천 결과를 제공합니다.

## 개발 환경에서 실행

Python 3.11 이상이 필요합니다. Debian 또는 Raspberry Pi OS에서는 `python3-venv`를 함께 설치합니다. SQLite는 Python 표준 라이브러리를 사용합니다.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
python -m flask --app app migrate
python -m flask --app app run --host 127.0.0.1 --port 5000
```

Windows PowerShell에서는 가상환경의 Python을 직접 지정해 실행합니다.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m flask --app app migrate
.\.venv\Scripts\python.exe -m flask --app app run --host 127.0.0.1 --port 5000
```

다른 터미널에서 `curl -fsS http://127.0.0.1:5000/health`를 실행하면 `{"status":"ok"}`가 예상됩니다. Windows PowerShell에서는 `curl.exe`를 사용합니다. `TRAP_DB_PATH`를 설정하지 않으면 프로젝트의 `instance/traps.sqlite3`를 사용합니다.

## 트랩, 위치, 설치 등록

아래 ID와 시각은 테스트용 예시입니다. 첫 설치나 재배치 시 실제 시작 시각을 시간대와 함께 입력하고 ESP32에도 같은 `deployment_id`를 설정합니다.

```sh
python -m flask --app app registry trap trap-01 '현장 트랩' --empty-g 2 --low-g 10 --interval 60
python -m flask --app app registry location loc-01 '초기 설치 지점'
python -m flask --app app registry location loc-02 '후보 지점'
python -m flask --app app registry deploy dep-001 trap-01 loc-01 rat '2026-11-25T09:00:00+09:00'
```

트랩을 옮기거나 목표종을 바꿀 때 `registry deploy`에 새 설치 ID를 입력합니다. 기존 설치는 새 설치 시작 시각에 종료되며, 그 전에 관측한 지연 이벤트는 기존 설치 ID로 받을 수 있습니다.

## 검증 명령

```sh
python -m unittest discover -s tests -v
python -m unittest discover -s tests -v -k test_csv_to_recommendation_round_trip
```

두 번째 명령은 임시 DB에서 모의 ESP32 이벤트 저장, PC CSV 읽기, PC 추천 등록, 대시보드가 사용할 조회 API 응답까지 확인합니다. 테스트용 토큰과 데이터는 임시 환경에 생성됩니다.

## 설정과 문서

운영 환경 변수 예시는 [.env.example](.env.example)에 있습니다. 로컬 개발에서는 값을 셸 환경 변수에 설정하며, 운영 systemd 유닛은 `/etc/iot-trap/backend.env`를 읽습니다. 토큰은 장치별 키, PC 읽기 키, PC 추천 쓰기 키를 각각 사용합니다.

- ESP32 MQTT 중계: `python -m app.mqtt_bridge` (설정은 [배포 문서](docs/deploy.md))
- [Pi 설치, SSH, Gunicorn, systemd, 백업 및 복원](docs/deploy.md)
- [ESP32, PC 분석, 대시보드 API 계약](docs/api.md)
- [단계별 구현과 검증 현황](docs/verification.md)
