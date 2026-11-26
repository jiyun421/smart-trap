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

## 데이터 구분 원칙

- `data/raw/actual/`: 실제 센서/감지 데이터 (Git 제외)
- `data/synthetic/`: 가상 포획 데이터 (시뮬레이션, 실제 포획 실적 아님)
- `data/external/`: 외부 공개 데이터셋 (설치류 GPS, 프라이부르크 카메라트랩). 추천 방식 검증용이며 출처는 각 파일 README 참고

## 외부 공개 데이터 기반 검증

    python -m src.movement_eval          # 설치류 GPS: 칸 단위 활동 예측
    python -m src.movement_ml            # 같은 분할에서 ML 비교
    python -m src.urban_camera_eval      # 프라이부르크 쥐 카메라트랩: 지점 단위 예측

결과 JSON은 `data/processed/`에 저장됩니다 (Git 제외, 재생성 가능).
