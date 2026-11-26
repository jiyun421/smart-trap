# 스마트 트랩 API 명세 (v1.0)

> **참고: 실제 연동 계약은 `backend/docs/api.md`입니다.** 이 문서는 Mock 모드(`/api/v1`, `pc/data/mock`)용 초안으로만 남아 있습니다. 실제 백엔드와의 차이는 `pc/src/backend_client.py`(PC→백엔드)와 `pc/dashboard/js/adapter.js`(백엔드→대시보드)가 변환합니다.

> 상태: **v1.0 - PC 담당 측에서 확정한 명세**. 이 문서를 Raspberry Pi 담당자에게 전달해 구현 가능 여부를 확인받는다. Pi 측에서 변경 요청이 오면 이 문서를 수정하고 버전을 올린다. 그 전까지 실제 연동은 이 명세를 따르는 Mock 데이터로 개발한다.

---

## 1. 공통 규약

| 항목      | 제안                                                               |
| --------- | ------------------------------------------------------------------ |
| Base URL  | `http://<RPI_IP>:<PORT>/api/v1`                                    |
| 형식      | 요청/응답 모두 `application/json; charset=utf-8`                   |
| 인증      | 초기에는 없음(같은 내부망 전제). 필요 시 헤더 `X-API-Key`          |
| 시각 형식 | ISO 8601, 한국 시간대 오프셋 포함: `2026-11-23T14:05:30+09:00`     |
| 필드명    | `snake_case`                                                       |
| 트랩 ID   | 문자열 `TRAP-01`, `TRAP-02` ...                                    |
| 위치 ID   | 문자열 `LOC-A`, `LOC-B` ...                                        |
| 결측값    | 측정하지 못한 값은 **`null`**. 0, 빈 문자열, -1로 대체하지 않는다. |
| 열거형 값 | 소문자 영문 (`rat`, `non_rat`, `open` ...)                         |

### 1-1. 페이지네이션 / 조회 기간 (목록 조회 공통)

쿼리 파라미터:

| 이름        | 설명                    | 기본값 |
| ----------- | ----------------------- | ------ |
| `from`      | 조회 시작 시각 (포함)   | 7일 전 |
| `to`        | 조회 종료 시각 (미포함) | 현재   |
| `page`      | 페이지 번호(1부터)      | 1      |
| `page_size` | 페이지 크기 (최대 1000) | 100    |
| `trap_id`   | 트랩 필터 (선택)        | 전체   |

목록 응답 공통 구조:

```json
{
  "data": [ ... ],
  "meta": { "page": 1, "page_size": 100, "total": 2345, "from": "2026-11-16T00:00:00+09:00", "to": "2026-11-23T00:00:00+09:00" }
}
```

정렬은 시각 오름차순(`timestamp` 또는 `detected_at` 기준) 고정.

### 1-2. 오류 응답 형식

모든 오류는 HTTP 상태 코드와 아래 본문을 사용한다.

```json
{
  "error": {
    "code": "INVALID_PARAMETER",
    "message": "from must be earlier than to",
    "details": { "field": "from" }
  }
}
```

| HTTP | code                 | 의미                       |
| ---- | -------------------- | -------------------------- |
| 400  | `INVALID_PARAMETER`  | 파라미터/본문 형식 오류    |
| 401  | `UNAUTHORIZED`       | 인증 실패 (인증 도입 시)   |
| 404  | `NOT_FOUND`          | 대상 없음                  |
| 409  | `DUPLICATE_RESOURCE` | 이미 존재하는 `run_id` 등  |
| 422  | `VALIDATION_FAILED`  | 형식은 맞으나 값 규칙 위반 |
| 500  | `INTERNAL_ERROR`     | 서버 내부 오류             |

---

## 2. 조회 API (PC → Pi, GET)

### 2-1. `GET /health`

서버 상태 확인(연결 테스트용).

```json
{ "status": "ok", "server_time": "2026-11-23T14:05:30+09:00" }
```

### 2-2. `GET /traps` — 트랩 목록 및 현재 상태

```json
{
  "data": [
    {
      "trap_id": "TRAP-01",
      "location_id": "LOC-A",
      "installed_at": "2026-11-01T09:00:00+09:00",
      "status": "operating",
      "door_state": "closed",
      "last_seen_at": "2026-11-23T14:05:00+09:00"
    }
  ]
}
```

| 필드           | 자료형           | 설명                                                                                                                                                          |
| -------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `trap_id`      | string           | 트랩 ID                                                                                                                                                       |
| `location_id`  | string           | **현재** 설치 위치 ID                                                                                                                                         |
| `installed_at` | string(datetime) | 현재 위치에 설치한 시각                                                                                                                                       |
| `status`       | string           | `recommended`(재배치 권고) / `keep`(유지) / `insufficient_data`(데이터 부족, 추천 확정 안 함) / `device_check`(장치 점검 권고, v1.1 추가·Pi 담당자 확인 필요) |
| `door_state`   | string \| null   | `open` / `closed` / `null`(미확인)                                                                                                                            |
| `last_seen_at` | string \| null   | 마지막 통신 시각                                                                                                                                              |

### 2-3. `GET /locations` — 위치 목록

```json
{
  "data": [
    {
      "location_id": "LOC-A",
      "name": "주방 입구",
      "is_candidate": false,
      "x": null,
      "y": null
    }
  ]
}
```

- `is_candidate`: 아직 트랩을 설치한 적 없는 **후보 위치**이면 `true`. (추천 시 기존 위치와 신규 후보를 구분하기 위함)
- `x`, `y`: 도면 좌표(없으면 `null`).

### 2-4. `GET /trap-location-history` — 트랩 위치 변경 이력

트랩이 어느 기간에 어느 위치에 있었는지 알아야 위치별 성과를 계산할 수 있다.

```json
{
  "data": [
    {
      "trap_id": "TRAP-01",
      "location_id": "LOC-A",
      "start_at": "2026-11-01T09:00:00+09:00",
      "end_at": "2026-11-15T18:00:00+09:00"
    }
  ]
}
```

`end_at`이 `null`이면 현재도 해당 위치에 설치 중. 공통 파라미터 중 `trap_id`만 사용(기간 필터 불필요).

### 2-5. `GET /sensor-readings` — 환경/센서 측정값

공통 쿼리 파라미터 사용.

```json
{
  "data": [
    {
      "reading_id": 10231,
      "trap_id": "TRAP-01",
      "measured_at": "2026-11-23T14:00:00+09:00",
      "temperature_c": 22.5,
      "humidity_pct": 48.1,
      "tvoc_ppb": 120,
      "eco2_ppm": 450,
      "load_cell_g": null
    }
  ],
  "meta": { "...": "..." }
}
```

| 필드            | 자료형          | 단위 | 비고                  |
| --------------- | --------------- | ---- | --------------------- |
| `reading_id`    | integer         | -    | 고유 ID (중복 제거용) |
| `trap_id`       | string          | -    |                       |
| `measured_at`   | string          | -    | 측정 시각             |
| `temperature_c` | number \| null  | ℃    |                       |
| `humidity_pct`  | number \| null  | %    |                       |
| `tvoc_ppb`      | integer \| null | ppb  |                       |
| `eco2_ppm`      | integer \| null | ppm  |                       |
| `load_cell_g`   | number \| null  | g    | 로드셀 측정값         |

### 2-6. `GET /detection-events` — 감지 이벤트

**이벤트 정의 제안:** 적외선 센서가 동물을 감지한 시점부터 카메라 분류 결과가 나올 때까지를 **1건의 이벤트**로 본다. 같은 동물의 반복 감지는 Pi(또는 ESP32)에서 **재감지 억제 시간(cooldown, 예: 60초)** 안에 들어오면 같은 이벤트로 묶는다.

```json
{
  "data": [
    {
      "event_id": 55012,
      "trap_id": "TRAP-01",
      "detected_at": "2026-11-23T03:12:41+09:00",
      "ir_detected": true,
      "classification": "rat",
      "confidence": 0.91
    }
  ],
  "meta": { "...": "..." }
}
```

| 필드             | 자료형         | 설명                                         |
| ---------------- | -------------- | -------------------------------------------- |
| `event_id`       | integer        | 고유 ID                                      |
| `trap_id`        | string         |                                              |
| `detected_at`    | string         | 감지 시각                                    |
| `ir_detected`    | boolean        | 적외선 감지 여부                             |
| `classification` | string \| null | `rat` / `non_rat` / `null`(분류 실패·미수행) |
| `confidence`     | number \| null | 0.0 ~ 1.0                                    |

> 카메라가 `rat`로 분류한 것은 **포획이 아니다**. 실제 포획 정보는 이 API에 없다.

### 2-7. `GET /trap-status-logs` — 트랩 작동 상태 변경 이력

작동 시간(운영 시간) 계산용. **상태가 바뀔 때마다 1건** 기록한다고 가정.

```json
{
  "data": [
    {
      "log_id": 801,
      "trap_id": "TRAP-01",
      "changed_at": "2026-11-23T09:00:00+09:00",
      "status": "operating",
      "door_state": "closed"
    }
  ],
  "meta": { "...": "..." }
}
```

`status`/`door_state` 값은 2-2와 동일.

---

## 3. 추천 결과 API

### 3-1. `POST /recommendations` — 추천 결과 저장 (PC → Pi)

한 번의 알고리즘 실행(run) 결과를 한 번에 전송한다.

요청:

```json
{
  "run_id": "RUN-20261123-140530",
  "generated_at": "2026-11-23T14:05:30+09:00",
  "analysis_period": {
    "from": "2026-11-09T00:00:00+09:00",
    "to": "2026-11-23T00:00:00+09:00"
  },
  "algorithm_version": "score-v0.1",
  "data_basis": {
    "detection_data": "actual",
    "capture_data": "synthetic",
    "is_simulation_based": true,
    "note": "포획 관련 수치는 가상 데이터 기반 추정이며 실제 포획 실적이 아님"
  },
  "recommendations": [
    {
      "trap_id": "TRAP-02",
      "current_location_id": "LOC-B",
      "recommended_location_id": "LOC-A",
      "recommended_location_type": "existing",
      "relocate": true,
      "status": "recommended",
      "priority": 1,
      "score": 0.82,
      "current_location_score": 0.35,
      "reasons": [
        "현재 위치는 감지 대비 가상 포획 전환율이 낮음",
        "추천 위치는 감지 빈도와 가상 포획 성과가 모두 높음"
      ],
      "actual_stats": {
        "operating_hours": 312.5,
        "rat_detections": 41,
        "non_rat_detections": 5,
        "rat_detections_per_hour": 0.131
      },
      "simulated_stats": {
        "captures": 6,
        "capture_conversion_rate": 0.146,
        "captures_per_hour": 0.019
      }
    }
  ]
}
```

필드 설명:

| 필드                               | 자료형          | 설명                                                                                          |
| ---------------------------------- | --------------- | --------------------------------------------------------------------------------------------- |
| `run_id`                           | string          | 실행 고유 ID (중복 전송 방지 키)                                                              |
| `generated_at`                     | string          | 추천 생성 시각                                                                                |
| `analysis_period`                  | object          | 분석 기간                                                                                     |
| `algorithm_version`                | string          | 알고리즘 버전                                                                                 |
| `data_basis`                       | object          | 데이터 출처 구분. `is_simulation_based`가 `true`면 대시보드에 "시뮬레이션 기반" 표시          |
| `status`                           | string          | `recommended`(재배치 권고) / `keep`(유지) / `insufficient_data`(데이터 부족, 추천 확정 안 함) |
| `relocate`                         | boolean         | `status == recommended`일 때만 `true`                                                         |
| `recommended_location_id`          | string \| null  | `keep`/`insufficient_data`이면 `null`                                                         |
| `recommended_location_type`        | string \| null  | `existing`(설치 이력 있음) / `new_candidate`(설치 이력 없음, 예측 불확실)                     |
| `priority`                         | integer \| null | 1이 가장 높음                                                                                 |
| `score`, `current_location_score`  | number \| null  | 0~1                                                                                           |
| `reasons`                          | string[]        | 추천 근거                                                                                     |
| `actual_stats` / `simulated_stats` | object          | **실제 데이터**와 **가상 데이터** 통계를 분리                                                 |

성공 응답 `201 Created`:

```json
{
  "run_id": "RUN-20261123-140530",
  "saved_count": 3,
  "saved_at": "2026-11-23T14:05:31+09:00"
}
```

- 같은 `run_id`를 다시 보내면 `409 DUPLICATE_RESOURCE`. (덮어쓰기는 하지 않음)
- 본문이 위 구조에 맞지 않으면 `422 VALIDATION_FAILED`.

### 3-2. `GET /recommendations` — 저장된 추천 조회

| 쿼리                | 설명                           |
| ------------------- | ------------------------------ |
| `run_id`            | 특정 실행 조회                 |
| `latest=true`       | 가장 최근 실행 1건 (기본 동작) |
| `page`, `page_size` | 실행 이력 목록 조회 시         |

응답 본문은 3-1 요청 본문과 **동일 구조**(`run_id` 단위)에 `saved_at`만 추가. 대시보드와 재조회 테스트에서 그대로 사용한다.

---

## 4. 가상 포획 데이터 표시 관련

대시보드 요구사항에는 "가상 포획 이력/추이 표시"가 있다. 대시보드는 Pi에서 제공되므로 가상 포획 데이터가 Pi에서 조회 가능해야 한다. 방법은 두 가지다.

- **방법 A (제안)**: PC가 가상 포획 요약을 `POST /simulated-captures`로 Pi에 저장하고, 대시보드는 `GET /simulated-captures`로 조회한다. 모든 레코드에 `"data_source": "synthetic"`을 포함한다.
- **방법 B**: 가상 포획 데이터를 정적 JSON 파일로 만들어 대시보드 폴더에 함께 배포한다. Pi 서버 변경이 필요 없다.

**확정: 방법 B로 시작한다.** 가상 포획 데이터는 정적 JSON 파일로 만들어 대시보드와 함께 배포하며, Pi 서버 변경은 필요 없다. 방법 A(`/simulated-captures`)는 추후 확장 시 별도 명세로 추가한다.

> 가상 포획 데이터는 실제 감지/센서 테이블에 **섞어 저장하지 않는다**. 별도 리소스 또는 `data_source` 구분 필드로 항상 분리한다.

---

## 5. 확정 사항 요약

| #   | 항목             | 확정 내용                                                                                      |
| --- | ---------------- | ---------------------------------------------------------------------------------------------- |
| 1   | 포트 / 인증      | 포트는 Pi 서버 실제 설정값 사용(`<PORT>`). 인증 없음(내부망). 필요해지면 `X-API-Key` 추가      |
| 2   | ID 형식          | 트랩 `TRAP-01`, 위치 `LOC-A`                                                                   |
| 3   | 감지 이벤트      | IR 감지~카메라 분류 완료를 1건으로 정의. 반복 감지는 **Pi에서 60초 재감지 억제 시간**으로 묶음 |
| 4   | 후보 위치        | 팀이 도면 기준으로 정하고, Pi 담당자가 `/locations`에 `is_candidate=true`로 등록               |
| 5   | 상태 이력        | 상태가 **변경될 때만** 기록                                                                    |
| 6   | 측정 주기 / 단위 | 주기는 API 규칙에 영향 없음(레코드마다 `measured_at` 포함). 로드셀 단위는 g                    |
| 7   | `run_id` 중복    | 409로 거부, 덮어쓰기 없음                                                                      |
| 8   | 가상 포획 제공   | 방법 B (정적 JSON 파일, 대시보드와 함께 배포)                                                  |
| 9   | 정렬 / 페이지    | 시각 오름차순, `page_size` 기본 100, 최대 1000                                                 |
