"""서버의 실제 기록으로 추천을 다시 계산해 저장한다. 하루 한 번 실행하는 것을 전제로 한다(backend/docs/deploy.md).

backend_import(서버 기록 → 일별 요약) -> mvp_dataset(실제 트랩 + 가상 트랩) -> export_recommendations(저장).
- 기간은 어제까지의 최근 days일(KST)이다. 가상 시나리오는 날짜를 옮겨 이 기간에 맞춘다.
- 가상 트랩의 값은 매번 같으므로, 갱신으로 달라지는 입력은 실제 트랩의 기록뿐이다.
- 실제 트랩의 데이터가 없으면 아무것도 저장하지 않고 실패한다(이전 추천이 그대로 남는다).
실행: python -m src.update_recommendations  (환경 변수 TRAP_API_URL, TRAP_READ_TOKEN, TRAP_RECOMMENDATION_TOKEN)
"""
import argparse
import os
from datetime import datetime, timedelta

import pandas as pd

from src.backend_client import backend_client
from src.backend_import import build_summary, fetch_backend_data
from src.export_recommendations import KST, export_recommendations
from src.mvp_dataset import build_mvp_summary
from src.synthetic_data import generate_scenario

DAYS = 28


def update(base_url, read_token=None, write_token=None, now=None, days=DAYS, session=None):
    """추천을 계산해 서버에 저장하고 보낸 payload를 돌려준다."""
    now = now or datetime.now(KST)
    end = now.astimezone(KST).date()  # 미포함: 아직 끝나지 않은 오늘은 쓰지 않는다
    start = end - timedelta(days=days)
    events, traps, deployments = fetch_backend_data(base_url, start.isoformat(), end.isoformat(), read_token,
                                                    session=session)
    actual, _ = build_summary(events, traps, deployments, start.isoformat(), end.isoformat())

    virtual = generate_scenario(write=False)["trap_day_summary"]
    dates = pd.to_datetime(virtual["date"])
    dates += pd.Timestamp(end - timedelta(days=1)) - dates.max()
    virtual = virtual.assign(date=dates.dt.strftime("%Y-%m-%d"))
    virtual = virtual[virtual["date"] >= start.isoformat()]

    client = backend_client(base_url, read_token=read_token, write_token=write_token, session=session)
    payload, _ = export_recommendations(build_mvp_summary(actual, virtual), client, now=now)
    return payload


def main():
    p = argparse.ArgumentParser(description="서버의 실제 기록으로 추천을 다시 계산해 저장한다.")
    p.add_argument("--base-url", default=os.environ.get("TRAP_API_URL", "http://127.0.0.1:5000"))
    p.add_argument("--days", type=int, default=DAYS, help="어제까지 며칠을 볼지")
    a = p.parse_args()
    payload = update(a.base_url, os.environ.get("TRAP_READ_TOKEN"), os.environ.get("TRAP_RECOMMENDATION_TOKEN"),
                     days=a.days)
    for r in payload["recommendations"]:
        print(r["trap_id"], r["status"], r["recommended_location_id"] or "")


if __name__ == "__main__":
    main()
