# ESP32에서 Pi의 SQLite 저장 확인

Arduino Nano ESP32의 칩 내부 온도를 테스트 값으로 보낸다. 이벤트 ID는 `chip-test-`로 시작한다. 실제 주변 온도 측정에는 외부 센서를 사용한다.

1. Pi 백엔드에 `trap-01`과 해당 트랩의 활성 설치 `dep-001`을 등록한다.
2. 이 폴더의 `secrets.example.h`를 `secrets.h`로 복사한다. Pi 주소, Wi-Fi 이름과 비밀번호, `trap-01` 장치 토큰을 복사본에 입력한다.
3. Arduino IDE에서 `esp32_storage_check.ino`를 열고 Arduino Nano ESP32에 업로드한다. Wi-Fi에서 Pi와 인터넷 시간 서버(NTP)에 접근할 수 있어야 한다.
4. 시리얼 모니터를 115200 baud로 열고 보드를 한 번 리셋한다. 헬스 체크는 HTTP 200, 첫 저장은 HTTP 201, 동일 이벤트 재전송은 HTTP 200과 `duplicate: true`를 반환한다.
5. Pi에서 아래 명령으로 최근 테스트 행을 읽어 시리얼 모니터의 이벤트 ID 및 온도와 대조한다.

```bash
sudo -u iot-trap sqlite3 -readonly -header -column /var/lib/iot-trap/traps.sqlite3 \
  "SELECT event_id, temperature_c, observed_at FROM trap_events WHERE trap_id='trap-01' AND deployment_id='dep-001' AND event_id LIKE 'chip-test-%' ORDER BY received_at DESC LIMIT 1;"
```
