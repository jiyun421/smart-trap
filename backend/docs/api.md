# ESP32, PC 및 대시보드 API

모든 `/api` 요청에 `Authorization: Bearer <토큰>`을 보냅니다. 장치 토큰 하나는 트랩 하나에 대응합니다. POST 요청은 `application/json`을 사용하고 본문은 64 KiB 이하입니다. 헬스 체크 `GET /health`는 인증 없이 `200`과 `{"status":"ok"}` 또는 `503`과 `{"status":"unavailable"}`을 반환합니다.

| 경로                              | 접근 토큰 | 응답                                                           |
| --------------------------------- | --------- | -------------------------------------------------------------- |
| `POST /api/sensor/data`           | 장치      | 이벤트 ID, 재전송 여부                                         |
| `GET /api/traps`                  | 읽기      | 트랩 설정과 활성 설치 식별자                                   |
| `GET /api/traps/<trap_id>/status` | 읽기      | 설치, 연결, 미끼, 필드별 최신 관측, 해당 설치의 최근 확인 포획 |
| `GET /api/locations`              | 읽기      | 등록 위치와 위치별 활성 트랩 수                                |
| `GET /api/readings`               | 읽기      | 환경값이 하나 이상 기록된 이벤트                               |
| `GET /api/visits`                 | 읽기      | 설치·방문 ID별 진입과 처리 결과                                |
| `GET /api/captures`               | 읽기      | 확인 포획 이력                                                 |
| `GET /api/stats/daily`            | 읽기      | 일자·트랩별 집계                                               |
| `GET /api/export/events.csv`      | 읽기      | 분석용 이벤트 CSV                                              |
| `POST /api/recommendations`       | 추천 쓰기 | 실행 ID, 재전송 여부                                           |
| `GET /api/recommendations`        | 읽기      | 추천 실행 이력                                                 |
| `GET /api/recommendations/latest` | 읽기      | 필터에 맞는 가장 최근 추천 실행                                |

## 공통 계약

장치, 설치, 위치, 이벤트, 방문, 실행과 종 코드는 영문 대소문자 또는 숫자로 시작하는 1~128자의 식별자입니다. 이후에는 영문자, 숫자, `_`, `.`, `:`, `-`를 사용할 수 있습니다. 팀이 같은 종 코드를 사용해야 하며 코드에서 대소문자를 구분합니다. 분류 실패는 `unknown`입니다.

시간은 시간대가 포함된 RFC 3339로 받으며 소수점 이하는 최대 6자리입니다. UTC의 고정 소수점 6자리와 `Z`로 반환합니다. 조회에서 `from`은 포함하고 `to`는 제외합니다. URL의 `+`는 `%2B`로 인코딩하거나 `Z` 형식을 사용합니다.

POST 저장은 `201`, 같은 ID에 같은 정규화 내용을 재전송하면 `200`입니다. 같은 ID에 다른 내용을 보내면 `409`입니다. 오류 응답은 `{"error":{"code":"invalid_input","message":"..."}}` 형태입니다. 토큰 없음·불일치는 `401`, 다른 역할이나 다른 트랩 키는 `403`입니다. 미등록 참조는 `404`, 부적합한 입력은 `400`, 본문 크기와 형식 위반은 각각 `413`, `415`입니다. 잠금이나 DB 장애는 `503`입니다.

## ESP32 수신

```json
{
  "schema_version": 1,
  "trap_id": "trap-01",
  "deployment_id": "dep-001",
  "event_id": "fce1d636-ef7c-44db-993d-303222fb3e03",
  "event_type": "visit_resolved",
  "observed_at": "2026-11-25T21:32:15+09:00",
  "visit_id": "visit-001",
  "species_code": "rat",
  "confidence": 0.93,
  "door_state": "closed",
  "outcome": "unconfirmed",
  "env": {
    "temperature_c": 17.2,
    "humidity_pct": 66.4,
    "illuminance_lux": 4.3,
    "bait_g": 24.1,
    "eco2_ppm": 450,
    "tvoc_ppb": 12
  }
}
```

공통 필드는 `schema_version` (`1`), `trap_id`, `deployment_id`, `event_id`, `event_type`, `observed_at`입니다.

| 이벤트           | 필수 관측값과 조건                                                                                 |
| ---------------- | -------------------------------------------------------------------------------------------------- |
| `telemetry`      | `env` 하위 관측값, `door_state`, `occupancy_state` 중 하나 이상                                    |
| `entry_detected` | `visit_id`. 측정한 환경·도어·점유값을 첨부할 수 있음                                               |
| `visit_resolved` | `visit_id`, `species_code`, `door_state`, `outcome`. `confidence`, `occupancy_state`, `env`는 선택 |

`door_state`는 `open`, `closed`, `unknown`이고, `occupancy_state`는 `occupied`, `empty`, `unknown`입니다. `outcome`은 `capture_confirmed`, `release_confirmed`, `unconfirmed`, `failed`입니다. 확인 결과에는 팀이 정의한 `outcome_evidence`를 비어 있지 않은 문자열 또는 JSON 객체로 전송하고, `observed_at`은 확인 시각을 사용합니다. 도어 닫힘 또는 목표종 분류만 확인한 상황의 `outcome`은 `unconfirmed`입니다. `eco2_ppm`, `tvoc_ppb`는 가스 센서의 추정값이며 참고용입니다. 환경 측정값과 신뢰도는 미측정 시 생략하거나 `null`을 전송합니다.

부팅 시 장치 시계를 동기화하고 주기를 트랩 설정과 맞춥니다. 타임아웃이나 `5xx` 발생 시 같은 `event_id`, `deployment_id`, `observed_at`, 관측값을 보존해 재시도합니다. `Retry-After`가 있으면 반영하고, 대기열은 지수 백오프와 임의 지연을 사용합니다. `201` 또는 `200` 수신 후 대기열에서 제거하고, `4xx`는 원인과 함께 기록합니다. 진입과 처리는 같은 `visit_id`를 쓰며 도착 순서가 바뀔 수 있습니다. 재배치 전에 큐에 넣은 이벤트는 원래 설치 ID를 유지합니다.

## ESP32 MQTT 이벤트

현재 ESP32 펌웨어는 위 HTTP 형식 대신 `trap/v1/<trap_id>/event`로 발행하며, Pi의 중계(`app.mqtt_bridge`)가 변환합니다.

| `result` | 저장되는 이벤트                          | 종 코드   |
| -------- | ---------------------------------------- | --------- |
| `target` | `entry_detected` + `visit_resolved`      | `rat`     |
| `other`  | `entry_detected` + `visit_resolved`      | `non_rat` |
| `fail`   | `entry_detected` + `visit_resolved`      | `unknown` |
| `empty`  | `telemetry`, `occupancy_state`는 `empty` | 없음      |
| `periodic` | `telemetry`                            | 없음      |

`temp_c`, `humidity_pct`, `lux`, `load_g`, `eco2`, `tvoc`는 `env`의 `temperature_c`, `humidity_pct`, `illuminance_lux`, `bait_g`, `eco2_ppm`, `tvoc_ppb`가 됩니다. `null`과 음수 `load_g`는 뺍니다. 문 상태 `between`은 `unknown`입니다. `observed_at`은 중계의 수신 시각, `outcome`은 `unconfirmed`입니다. `location`, `command`, `species`, `battery_mv`는 저장하지 않으며 위치는 등록된 설치를 따릅니다. 같은 `boot`·`uptimeMs`·`result`가 10분 안에 다시 오면 재전송으로 보고 무시합니다.

## 조회와 집계

- `/readings`, `/visits`, `/captures`는 `trap_id`, `from`, `to`, `limit`, `offset`을 지원합니다. 결과는 최신 관측부터 정렬하고 동률에는 식별자를 사용합니다. 기본 `limit`는 100, 최대 500입니다. `next_offset`을 다음 페이지의 `offset`으로 사용합니다.
- `GET /api/deployments`는 재배치 이력을 포함한 설치 이력을 `{"items": [...]}`로 반환합니다(`trap_id` 필터 가능, 시작 시각순). 종료되지 않은 설치는 `ended_at`이 `null`입니다.
- `TRAP_READ_AUTH=off`로 설정하면 조회(read) 역할에 토큰을 요구하지 않습니다(기본값 `required`). 장치·추천 쓰기 토큰은 그대로 필요합니다. 신뢰하는 내부망에서 정적 대시보드가 토큰 없이 읽을 때만 사용합니다.
- `/visits`는 `species_code`를 추가로 받습니다. 한쪽 이벤트만 있으면 없는 쪽의 `entry` 또는 `resolution`은 `null`입니다. 기간 필터에는 진입 시각을 우선하고, 진입 미수신 시 처리 시각을 사용합니다. `/captures`는 포획 확인 시각을 사용합니다.
- 상태의 `connection_state`는 현재 설치에서 마지막으로 새 이벤트를 저장한 뒤 보고 주기의 3배까지 `online`, 이후 `offline`, 수신 이력이 없을 때 `unknown`입니다. 각 필드의 관측이 같은 시간 기준을 넘으면 `stale`입니다. 오래되거나 미측정된 미끼는 `unknown`이고, 현재 값이 소진 기준 이하이면 `empty`, 미끼 부족 기준 이하이면 `low`, 그보다 크면 `ok`입니다.
- 일자 통계는 `trap_id`, `from`, `to`, `tz`를 지원합니다. 기본 시간대는 `Asia/Seoul`이고, 기본 기간은 최근 7일입니다. 기간을 지정할 때 두 경계가 모두 필요하며 최대 366일입니다. 해당 기간에 진입이나 포획 기록이 있는 일자·트랩만 반환됩니다. 진입은 진입 시각, 확인 포획은 확인 시각으로 집계합니다. 종 코드 `unknown`은 미분류로 집계하며 처리 결과가 없는 진입은 `pending_entries`로 집계합니다.
- CSV는 `trap_id`를 선택적으로 받고 `from`과 `to`를 요구하며 한 요청 최대 31일입니다. UTF-8로 출력하고, 결측치는 빈 셀입니다. `outcome_evidence`는 JSON 문자열 또는 객체로 인코딩합니다. 주기 보고는 CSV에 포함되며 보고가 없는 구간의 관측 여부는 불명으로 취급합니다.

```text
schema_version,trap_id,deployment_id,location_id,visit_id,event_id,event_type,observed_at,received_at,target_species,species_code,confidence,temperature_c,humidity_pct,illuminance_lux,bait_g,eco2_ppm,tvoc_ppb,door_state,occupancy_state,outcome,outcome_evidence
```

## PC 위치 추천

PC가 CSV 및 등록 위치를 읽어 분석을 실행하고 결과를 한 번에 등록합니다. 진입과 포획은 `prediction_kind`를 각각 `target_entry`, `target_capture`로 저장합니다. `ready`에는 등록된 후보 위치와 `score_type`이 필요하며, 후보별 `rank`와 `location_id`는 각각 유일해야 합니다. 점수는 0~1이며 `probability` 또는 `relative_score`로 해석합니다. `insufficient_data`는 `candidates: []`와 최상위 `reason`을 필수로 하고, `score_type`은 생략하거나 `null`을 사용합니다.

```json
{
  "run_id": "run-001",
  "trap_id": "trap-01",
  "target_species": "rat",
  "model_version": "location-model-1",
  "generated_at": "2026-11-26T00:00:00Z",
  "prediction_kind": "target_entry",
  "data_from": "2026-11-25T00:00:00Z",
  "data_to": "2026-11-26T00:00:00Z",
  "forecast_from": "2026-11-26T00:00:00Z",
  "forecast_to": "2026-11-27T00:00:00Z",
  "status": "ready",
  "score_type": "relative_score",
  "candidates": [
    {
      "location_id": "loc-02",
      "rank": 1,
      "score": 0.82,
      "reason": "PC 분석 결과"
    }
  ]
}
```

선택 필드 `data_basis`와 `details`를 받습니다. `data_basis`는 `detection_data`, `capture_data`(`actual`, `synthetic`, `mixed`, `unknown`), `is_simulation_based`(불리언), `note`를 모두 가지며, 대시보드가 가상 데이터 기반 결과를 구분하는 데 씁니다. `details`는 임의의 JSON 객체로 그대로 저장·반환하며, PC는 판정(`decision`: recommended, keep, device_check, insufficient_data) 등 PC 전용 값을 여기에 담습니다.

`GET /api/recommendations`와 `/latest`는 `trap_id`, `target_species`, `prediction_kind`로 필터링합니다. `/latest`는 생성 시각이 가장 최신인 실행을 반환합니다. 해당 실행이 자료 부족이면 그 상태와 사유를 그대로 제공합니다. 일치하는 실행이 없으면 `404`입니다.

```sh
curl -fsS -H "Authorization: Bearer $TRAP_READ_TOKEN" \
  'http://127.0.0.1:5000/api/export/events.csv?trap_id=trap-01&from=2026-11-25T00:00:00Z&to=2026-11-26T00:00:00Z' \
  -o events.csv
curl -fsS -H "Authorization: Bearer $TRAP_READ_TOKEN" \
  'http://127.0.0.1:5000/api/recommendations/latest?trap_id=trap-01&target_species=rat&prediction_kind=target_entry'
```

대시보드는 운영 환경에 맞춰 조회용 인증과 연동합니다. 장치 키와 추천 쓰기 키는 정적 파일에 넣지 않습니다. `/`와 빌드 에셋은 Flask가 제공하며, 대시보드는 같은 오리진의 상대 API 경로를 사용합니다.
