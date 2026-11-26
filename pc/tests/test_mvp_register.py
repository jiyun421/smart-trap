from src.mvp_register import register_commands
from src.synthetic_data import generate_scenario

NAMES = {"LOC-A": "주방 입구", "LOC-E": "쓰레기장 뒤"}


def test_registers_virtual_traps_locations_and_deployments_only():
    summary = generate_scenario(write=False)["trap_day_summary"]
    cmds = register_commands(summary, NAMES)
    text = "\n".join(cmds)
    assert "registry trap TRAP-01" not in text and "registry trap TRAP-02" in text  # 실제 트랩 제외
    assert "TRAP-05" not in text  # 철수한 트랩 제외
    assert "registry location LOC-E" in text  # 설치 이력 없는 후보 위치 포함
    order = [c.split()[4] for c in cmds]
    assert order == sorted(order, key=["trap", "location", "deploy"].index)  # 트랩 -> 위치 -> 설치 이력 순
    assert any("deploy dep-TRAP-02-2 TRAP-02 LOC-A rat" in c for c in cmds)  # 재배치는 새 설치 이력
