# smart-trap / pc

스마트 트랩 프로젝트의 PC 담당 코드: 데이터 분석, 트랩 재배치 추천 알고리즘, 웹 대시보드 프론트엔드.
이 폴더에서 명령을 실행합니다 (`cd pc`).

## 환경 설정

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python tests/check_env.py

## 실행과 테스트

    python -m pytest -q                  # Python 테스트
    node --test dashboard/tests          # 대시보드 모델 테스트
    python -m src.mock_server            # 목업 API + 대시보드: http://localhost:8000/dashboard/

## 실제 백엔드 연동 (backend/)

백엔드 실행은 `backend/README.md`를 따릅니다(Python 3.11 이상). 계약은 `backend/docs/api.md`입니다.

- 대시보드: 백엔드가 `TRAP_DASHBOARD_DIR`로 `pc/dashboard`를 제공하면 `dashboard/js/config.js`의 `apiBase`를 `"/"`(같은 오리진)로 설정합니다. `null`이면 Mock 데이터를 씁니다. 토큰 없이 읽으려면 백엔드에 `TRAP_READ_AUTH=off`가 필요합니다.
- 추천 저장: `from src.backend_client import backend_client` → `export_recommendations(summary, backend_client("http://<Pi>:5000", read_token=..., write_token=...))`. 트랩마다 run 하나로 변환되며 가상 데이터 표시(`data_basis`)와 실제/가상 통계는 `details`에 보존됩니다.
- 지도 좌표: 백엔드 위치에는 좌표가 없어 `config.js`의 `layout`(위치 ID → `{x, y}`)으로 지정합니다. 비어 있으면 추천 지도에 마커가 없습니다.
- 추천 갱신: `python -m src.update_recommendations`가 서버의 최근 28일 기록과 가상 트랩을 합쳐 추천을 계산해 저장합니다(토큰은 환경 변수 `TRAP_READ_TOKEN`, `TRAP_RECOMMENDATION_TOKEN`). Pi에서 하루 한 번 실행하는 설정은 `backend/docs/deploy.md`에 있습니다.
- 가상 트랩 표시: `config.js`의 `realTrapIds`(예: `["TRAP-01"]`)를 지정하면 그 밖의 트랩에 "가상"이 붙습니다. `null`이면 표시하지 않습니다.
- 가상 트랩 등록: 추천을 저장하려면 트랩·위치가 백엔드에 등록되어 있어야 합니다. `python -m src.mvp_register`가 가상 시나리오의 등록 명령(`flask registry ...`)을 출력합니다. 실제 트랩과 위치(예: `LOC-REAL-1`)는 따로 등록합니다. 가상 트랩은 센서 이벤트가 없어 대시보드에서 오프라인으로 보입니다.
- 센서 대응: eCO₂/TVOC는 `eco2_ppm`/`tvoc_ppb`(참고값, 보내지 않은 이벤트는 "—"), `load_cell_g`는 `bait_g`(미끼 무게)입니다.

## 데이터 구분 원칙

- `data/raw/actual/`: 실제 센서/감지 데이터 (Git 제외)
- `data/synthetic/`: 가상 포획 데이터 (시뮬레이션, 실제 포획 실적 아님)
- `data/external/`: 외부 공개 데이터셋 (설치류 GPS, 프라이부르크 카메라트랩). 추천 방식 검증용이며 출처는 각 파일 README 참고

## 외부 공개 데이터 기반 검증

    python -m src.movement_eval          # 설치류 GPS: 칸 단위 활동 예측
    python -m src.movement_ml            # 같은 분할에서 ML 비교
    python -m src.urban_camera_eval      # 프라이부르크 쥐 카메라트랩: 지점 단위 예측

결과 JSON은 `data/processed/`에 저장됩니다 (Git 제외, 재생성 가능).
