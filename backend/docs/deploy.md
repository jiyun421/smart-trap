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
