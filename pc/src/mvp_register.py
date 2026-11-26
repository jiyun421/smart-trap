"""가상 트랩·위치를 백엔드에 등록하는 `flask registry` 명령을 출력한다(백엔드에 직접 쓰지 않는다).

MVP에서는 실제 트랩(기본 TRAP-01) 하나만 실제 장치이고 나머지는 가상 시나리오다. 추천 결과를 백엔드에 저장하려면
추천에 나오는 트랩·위치가 백엔드에 등록되어 있어야 하므로, 가상 시나리오의 트랩·위치·설치 이력을 등록한다.
출력된 명령을 backend/ 폴더에서 (TRAP_DB_PATH 등 백엔드와 같은 환경변수로) 실행한다.
실제 트랩과 그 위치(예: LOC-REAL-1)는 이 스크립트가 다루지 않는다. 팀이 따로 등록한다.
사용: python -m src.mvp_register [--real-trap TRAP-01]
"""
import argparse
import json
import shlex
from pathlib import Path

import pandas as pd

from src.mvp_dataset import REAL_TRAP_ID
from src.synthetic_data import generate_scenario

NAMES = Path(__file__).resolve().parent.parent / "data" / "mock" / "locations.json"


def _names():
    data = json.loads(NAMES.read_text(encoding="utf-8"))
    items = data["data"]
    return {x["location_id"]: x["name"] for x in items}


def register_commands(summary, names, real_trap=REAL_TRAP_ID, empty_g=0, low_g=20, interval=60, species="rat"):
    """summary: 가상 시나리오 trap_day_summary. 반환: 셸 명령 문자열 목록(트랩 -> 위치 -> 설치 이력 순)."""
    s = summary[summary["trap_id"] != real_trap].sort_values(["trap_id", "date"])
    # 마지막 날짜에 행이 없는 트랩은 철수한 것이다. 백엔드 CLI는 설치 종료를 기록할 수 없어 등록하지 않는다.
    s = s[s["trap_id"].isin(s.loc[s["date"] == s["date"].max(), "trap_id"])]
    reg = "flask --app app registry"
    cmds = [f"{reg} trap {t} {shlex.quote(t)} --empty-g {empty_g} --low-g {low_g} --interval {interval}"
            for t in sorted(s["trap_id"].unique())]
    cmds += [f"{reg} location {l} {shlex.quote(names.get(l, l))}" for l in sorted(set(s["location_id"]) | set(names))]  # 설치 이력 없는 후보 위치 포함
    for trap, g in s.groupby("trap_id"):
        changed = g["location_id"].ne(g["location_id"].shift())  # 위치가 바뀐 날부터 새 설치 이력
        for n, (_, r) in enumerate(g[changed].iterrows(), 1):
            start = pd.Timestamp(r["date"]).tz_localize("Asia/Seoul").tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
            cmds.append(f"{reg} deploy dep-{trap}-{n} {trap} {r['location_id']} {species} {start}")
    return cmds


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--real-trap", default=REAL_TRAP_ID)
    a = p.parse_args()
    print("\n".join(register_commands(generate_scenario(write=False)["trap_day_summary"], _names(), a.real_trap)))


if __name__ == "__main__":
    main()
