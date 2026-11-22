// 실행: node --test dashboard/tests
const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../js/model.js");

const rec = (trap_id, status, extra = {}) => ({
  trap_id,
  current_location_id: "LOC-X",
  status,
  priority: null,
  ...extra,
});

test("정렬: 재배치(priority순) → 장치 점검 → 데이터 부족 → 유지, 원본 불변", () => {
  const input = [
    rec("T-1", "keep"),
    rec("T-2", "recommended", { priority: 2 }),
    rec("T-3", "insufficient_data"),
    rec("T-4", "device_check"),
    rec("T-5", "recommended", { priority: 1 }),
  ];
  const copy = JSON.stringify(input);
  assert.deepEqual(
    M.sortRecommendations(input).map((r) => r.trap_id),
    ["T-5", "T-2", "T-4", "T-3", "T-1"],
  );
  assert.equal(JSON.stringify(input), copy);
});

test("상태별 개수와 알 수 없는 상태", () => {
  const c = M.countByStatus([
    rec("a", "keep"),
    rec("b", "keep"),
    rec("c", "device_check"),
    rec("d", "bogus"),
  ]);
  assert.deepEqual(c, {
    recommended: 0,
    device_check: 1,
    insufficient_data: 0,
    keep: 2,
  });
  assert.equal(M.statusMeta("bogus").label, "알 수 없음");
});

test("모든 상태에 아이콘과 라벨이 있다 (색만으로 구분하지 않음)", () => {
  Object.values(M.STATUS).forEach((s) => assert.ok(s.icon && s.label));
});

test("결측은 0이 아니라 —", () => {
  assert.equal(M.fmtNum(null), "—");
  assert.equal(M.fmtNum(undefined), "—");
  assert.equal(M.fmtNum(NaN), "—");
  assert.equal(M.fmtPct(null), "—");
  assert.equal(M.fmtCount(null), "—");
  assert.equal(M.fmtNum(0), "0.000"); // 실제 0은 0으로 표시
  assert.equal(M.fmtPct(0), "0.0%");
  assert.equal(M.fmtPct(0.3636), "36.4%");
});

test("날짜 표시는 타임존 변환 없이 KST 문자열 그대로", () => {
  assert.equal(M.fmtDateTime("2026-11-23T14:05:30+09:00"), "2026-11-23 14:05");
  assert.equal(M.fmtDateTime("garbage"), "—");
  assert.equal(M.fmtDateTime(null), "—");
});

test("분석 기간: to는 배타적이라 마지막 날은 하루 전", () => {
  assert.equal(
    M.periodLabel({
      from: "2026-11-09T00:00:00+09:00",
      to: "2026-12-07T00:00:00+09:00",
    }),
    "2026-11-09 ~ 2026-12-06 (28일)",
  );
  assert.equal(
    M.periodLabel({
      from: "2026-11-09T00:00:00+09:00",
      to: "2026-11-09T00:00:00+09:00",
    }),
    "—",
  );
  assert.equal(M.periodLabel(null), "—");
});

test("시뮬레이션 표시: 필드가 없으면 안전하게 시뮬레이션으로 본다", () => {
  assert.equal(M.basisInfo(undefined).simulated, true);
  assert.equal(M.basisInfo({}).simulated, true);
  assert.equal(M.basisInfo({ is_simulation_based: true, note: "N" }).note, "N");
  assert.equal(M.basisInfo({ is_simulation_based: false }).simulated, false);
});

test("차트 행: 결측값은 null 유지, 데이터 부족 표시", () => {
  const rows = M.chartRows(
    [
      rec("T-1", "keep", { v: 0.3 }),
      rec("T-2", "insufficient_data", { v: null }),
    ],
    (r) => r.v,
  );
  assert.deepEqual(
    rows.map((r) => r.value),
    [null, 0.3], // 데이터 부족(T-2)이 유지(T-1)보다 앞, 결측은 0이 아닌 null
  );
  assert.equal(rows[0].insufficient, true);
  assert.equal(rows[0].label, "T-2 @LOC-X");
});

test("감지 통계 제목은 실제/가상을 구분한다", () => {
  assert.equal(M.detectionLabel({ detection_data: "actual" }), "실제 감지 데이터");
  assert.equal(M.detectionLabel({ detection_data: "synthetic" }), "가상 감지 데이터");
  assert.equal(M.detectionLabel({ detection_data: "mixed" }), "감지 데이터 (실제+가상 혼합)");
  assert.equal(M.detectionLabel(undefined), "감지 데이터");
});
