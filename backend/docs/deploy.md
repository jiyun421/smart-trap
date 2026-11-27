# Raspberry Pi 설치 및 운영

## Raspberry Pi OS와 SSH

이미 운영 중인 Pi는 기존 OS와 DB를 그대로 두고 현재 버전과 백업 상태를 확인합니다. 새 저장장치를 준비할 때 Raspberry Pi Imager에서 Raspberry Pi 5 및 Raspberry Pi OS Lite (64-bit)를 선택합니다. 호스트명, 로그인 계정, 네트워크와 SSH 공개키를 설정합니다. [Raspberry Pi Imager 공식 문서](https://www.raspberrypi.com/documentation/computers/imager.html)

같은 LAN의 PC에서 예시 계정과 IP를 실제 값으로 바꿔 접속하고, 운영체제 아키텍처와 Python을 확인합니다.

```sh
ssh pi-user@192.168.0.42
uname -m
python3 --version
hostname -I
```

실제 운영 주소는 장비 설치 때 `http://<Pi의 사설 LAN IP>:5000` 형식으로 기록해 ESP32 및 PC 담당자와 공유합니다.

## 의존성과 운영 서비스 설치

프로젝트 폴더에서 실행합니다. 운영 소스의 기준 경로는 `/opt/iot-trap`입니다.

```sh
sudo apt update
sudo apt install -y python3 python3-venv git sqlite3 curl tzdata
sudo install -d -m 0755 /opt/iot-trap
sudo cp -R app migrations deploy docs README.md requirements.txt .env.example /opt/iot-trap/
# 갱신 설치라면 복사 후 setup-pi.sh를 다시 실행하고 iot-trap과 iot-trap-mqtt를 재시작합니다.
cd /opt/iot-trap
sudo sh deploy/setup-pi.sh

getent group iot-trap >/dev/null || sudo groupadd --system iot-trap
id iot-trap >/dev/null 2>&1 || sudo useradd --system --gid iot-trap --home-dir /var/lib/iot-trap --shell /usr/sbin/nologin iot-trap
sudo install -d -m 0750 /etc/iot-trap
sudo test -f /etc/iot-trap/backend.env || sudo install -m 0600 .env.example /etc/iot-trap/backend.env
sudoedit /etc/iot-trap/backend.env
```

`TRAP_DEVICE_TOKENS`는 `{"trap-01":"발급한_장치_토큰"}` 형태입니다. `TRAP_READ_TOKEN`과 `TRAP_RECOMMENDATION_TOKEN`에도 각각 별도 값을 설정합니다. 내부망의 정적 대시보드가 토큰 없이 읽어야 하면 `TRAP_READ_AUTH=off`를 추가합니다(기본 `required`). 조회만 열리고 장치·추천 쓰기 토큰은 계속 필요하며, 이 경우 `TRAP_READ_TOKEN`은 생략할 수 있습니다. 각 토큰은 다음 명령으로 한 번씩 생성해 해당 장치나 PC에만 전달합니다.

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

유닛 기본값은 `0.0.0.0:5000`입니다. Pi에 여러 인터페이스가 있으면 환경 파일의 `TRAP_BIND`에 실제 사설 LAN IP와 포트를 지정합니다. 다른 네트워크에서 접속해야 할 경우 팀의 TLS 종단과 접근 제어를 구성합니다. Gunicorn은 워커 2개, 스레드 2개로 시작합니다. [Flask Gunicorn 배포 문서](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/)

```sh
sudo install -m 0644 deploy/iot-trap.service /etc/systemd/system/iot-trap.service
sudo systemctl daemon-reload
sudo systemctl enable --now iot-trap.service
sudo systemctl status iot-trap.service
sudo journalctl -u iot-trap.service -n 100 --no-pager
curl -fsS http://127.0.0.1:5000/health
```

서비스는 시작 전에 DB 마이그레이션을 적용하고 장애 종료 시 재시작합니다. PC에서 `curl -fsS 'http://<Pi-IP>:5000/health'`의 IP를 실제 값으로 바꿔 같은 응답이 나오는지 확인합니다. `TRAP_BIND`를 특정 IP로 지정했다면 Pi 자체에서도 그 IP로 확인합니다. 환경 파일이 바뀌면 `sudo systemctl restart iot-trap.service`를 실행합니다.

운영 DB에 트랩을 등록할 때 README의 명령 앞에 아래처럼 서비스 사용자 및 절대 DB 경로를 지정합니다. 위치와 설치 등록에도 동일한 접두사를 사용합니다.

```sh
sudo -u iot-trap env TRAP_DB_PATH=/var/lib/iot-trap/traps.sqlite3 \
  /opt/iot-trap/.venv/bin/flask --app app registry trap trap-01 '현장 트랩' \
  --empty-g 2 --low-g 10 --interval 60
```

PC 담당자의 대시보드 빌드를 `/opt/iot-trap/dashboard/dist`에 배치하고 `TRAP_DASHBOARD_DIR`에 같은 절대 경로를 지정합니다. `index.html`과 빌드 에셋을 해당 디렉터리에 두고 서비스가 읽을 수 있도록 권한을 부여합니다. 대시보드에서는 상대 경로 `/api/...`를 사용합니다.

이 저장소의 대시보드는 빌드 과정이 없습니다. 저장소 최상위에서 복사한 뒤, 복사본의 `apiBase`만 `"/"`로 바꿉니다(저장소의 `null`은 Mock 데이터용입니다). 서비스 환경 파일에 `TRAP_DASHBOARD_DIR=/opt/iot-trap/dashboard/dist`와 `TRAP_READ_AUTH=off`를 지정하고 `iot-trap.service`를 재시작합니다.

```sh
sudo mkdir -p /opt/iot-trap/dashboard/dist
sudo cp -R pc/dashboard/*.html pc/dashboard/css pc/dashboard/js pc/dashboard/assets /opt/iot-trap/dashboard/dist/
sudo sed -i 's/apiBase: null/apiBase: "\/"/' /opt/iot-trap/dashboard/dist/js/config.js
sudo chmod -R a+rX /opt/iot-trap/dashboard
```

## ESP32 MQTT 중계

ESP32는 `trap/v1/<trap_id>/event`로 MQTT 발행만 합니다. Pi의 mosquitto가 받고 `app.mqtt_bridge`가 `POST /api/sensor/data`로 옮깁니다. 펌웨어는 브로커 주소 `192.168.0.10:1883`, 계정 없음으로 고정되어 있으므로 공유기에서 Pi에 이 IP를 고정합니다.

```sh
sudo apt install -y mosquitto mosquitto-clients
sudo install -m 0644 deploy/mosquitto-trap.conf /etc/mosquitto/conf.d/trap.conf
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto
```

`/etc/iot-trap/backend.env`의 `TRAP_DEVICE_TOKENS`에 펌웨어의 트랩 ID를 대소문자까지 같게 넣습니다(예: `{"TRAP-01":"발급한_장치_토큰"}`). 중계는 이 토큰으로 저장하고, 설치 ID는 서버의 활성 설치를 조회해 채웁니다. `TRAP_READ_AUTH=required`이면 `TRAP_READ_TOKEN`도 필요합니다. 트랩과 설치를 서비스 사용자로 등록합니다. 주기 700초는 오프라인 판정(주기의 3배)을 35분으로 맞춘 값입니다. 설치 시작 시각은 첫 메시지를 받기 전이어야 합니다.

```sh
flask_registry() { sudo -u iot-trap env TRAP_DB_PATH=/var/lib/iot-trap/traps.sqlite3 /opt/iot-trap/.venv/bin/flask --app app registry "$@"; }
cd /opt/iot-trap
flask_registry trap TRAP-01 '현장 트랩' --empty-g 2 --low-g 10 --interval 700
flask_registry location z-kitchen '주방'
flask_registry deploy dep-TRAP-01-1 TRAP-01 z-kitchen rat "$(date +%Y-%m-%dT%H:%M:%S%:z)"
sudo install -m 0644 deploy/iot-trap-mqtt.service /etc/systemd/system/iot-trap-mqtt.service
sudo systemctl daemon-reload
sudo systemctl enable --now iot-trap-mqtt.service
```

`--empty-g`, `--low-g`는 예시입니다. 미끼 접시를 올리고 로드셀을 보정한 뒤 실제 무게에 맞춥니다.

ESP32 없이 확인할 때는 Pi에서 모의 메시지를 발행하고 중계 로그와 상태를 봅니다. 이 이벤트는 DB에 실제 기록으로 남습니다.

```sh
mosquitto_pub -h 127.0.0.1 -t trap/v1/TRAP-01/event -m '{"trapId":"TRAP-01","location":"z-kitchen","boot":1,"uptimeMs":1000,"result":"periodic","species":0,"command":"stay","door":"open","load_g":null,"temp_c":23.1,"humidity_pct":55.2,"lux":130.0,"battery_mv":null,"eco2":450,"tvoc":12}'
sudo journalctl -u iot-trap-mqtt.service -n 20 --no-pager
curl -fsS http://127.0.0.1:5000/api/traps/TRAP-01/status   # TRAP_READ_AUTH=off일 때
```

## SQLite 백업과 복원

SQLite CLI의 온라인 백업으로 WAL을 포함한 시점 일관성 있는 사본을 만듭니다. 아래 경로는 DB 기본 위치를 기준으로 합니다. 생성된 파일은 서비스 계정만 읽을 수 있게 관리하고 운영 장비 외부에도 별도 보관합니다. [SQLite CLI 문서](https://sqlite.org/cli.html)

```sh
sudo install -d -o iot-trap -g iot-trap -m 0700 /var/lib/iot-trap/backups
backup="/var/lib/iot-trap/backups/traps-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
sudo -u iot-trap sh -c 'umask 077; sqlite3 "$1" ".backup $2"' sh /var/lib/iot-trap/traps.sqlite3 "$backup"
sudo -u iot-trap sqlite3 -readonly "$backup" 'PRAGMA integrity_check;'
```

복원 시 사용할 백업을 먼저 검증하고 현재 DB를 위 명령으로 한 번 더 백업합니다. 서비스 중단 후 복원합니다. 백업 경로는 검증한 파일의 절대 경로로 바꿉니다.

```sh
backup=/var/lib/iot-trap/backups/선택한_백업.sqlite3
sudo -u iot-trap sqlite3 -readonly "$backup" 'PRAGMA integrity_check;'
sudo systemctl stop iot-trap.service
sudo -u iot-trap sqlite3 /var/lib/iot-trap/traps.sqlite3 ".restore $backup"
sudo -u iot-trap sqlite3 /var/lib/iot-trap/traps.sqlite3 'PRAGMA integrity_check;'
sudo systemctl start iot-trap.service
curl -fsS http://127.0.0.1:5000/health
```
