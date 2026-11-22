# smart-trap-pc

스마트 트랩 프로젝트의 PC 담당 코드: 데이터 분석, 트랩 재배치 추천 알고리즘, 웹 대시보드 프론트엔드.

## 환경 설정
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python tests/check_env.py

## 데이터 구분 원칙
- `data/raw/actual/`: 실제 센서/감지 데이터 (Git 제외)
- `data/synthetic/`: 가상 포획 데이터 (시뮬레이션, 실제 포획 실적 아님)
