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

// ---- 리디자인에서 추가된 함수 ----
const NOW = Date.parse("2026-05-10T12:00:00+09:00");

test("트랩 상태: 통신 없음/30분 초과 → 오프라인, 비정상·device_check → 점검 필요", () => {
  const t = (over) => ({ status: "operating", last_seen_at: "2026-05-10T11:50:00+09:00", ...over });
  assert.equal(M.trapState(t(), NOW), "ok");
  assert.equal(M.trapState(t({ last_seen_at: null }), NOW), "off");
  assert.equal(M.trapState(t({ last_seen_at: "2026-05-10T11:20:00+09:00" }), NOW), "off");
  assert.equal(M.trapState(t({ status: "maintenance" }), NOW), "warn");
  assert.equal(M.trapState(t(), NOW, { status: "device_check" }), "warn");
});

test("시간대별·일별 집계와 구간은 [from, to)", () => {
  const ev = [
    { detected_at: "2026-05-10T03:10:00+09:00" },
    { detected_at: "2026-05-10T03:50:00+09:00" },
    { detected_at: "2026-05-09T23:00:00+09:00" },
  ];
  const h = M.hourOfDay(ev);
  assert.equal(h.length, 24);
  assert.equal(h[3], 2);
  assert.equal(h[23], 1);
  const d = M.dailyCounts(ev, NOW, 2);
  assert.deepEqual(d.map((x) => x.count), [1, 2]);
  assert.equal(M.inWindow(ev, "detected_at", NOW - 86400000, NOW).length, 3);
  assert.equal(M.inWindow(ev, "detected_at", Date.parse("2026-05-10T03:50:00+09:00"), NOW).length, 1);
});

test("일별 평균: 데이터 없으면 0이 아니라 null, 결측값은 제외", () => {
  const r = [
    { measured_at: "2026-05-10T01:00:00+09:00", temperature_c: 10 },
    { measured_at: "2026-05-10T02:00:00+09:00", temperature_c: null },
    { measured_at: "2026-05-10T03:00:00+09:00", temperature_c: 20 },
  ];
  assert.deepEqual(M.dailyAvg(r, "temperature_c", ["2026-05-09", "2026-05-10"]), [null, 15]);
});

test("피어슨: 완전 상관 1, 짝 3개 미만·분산 0은 null", () => {
  assert.ok(Math.abs(M.pearson([1, 2, 3], [2, 4, 6]) - 1) < 1e-9);
  assert.equal(M.pearson([1, 2], [1, 2]), null);
  assert.equal(M.pearson([1, 2, 3], [5, 5, 5]), null);
  assert.ok(Math.abs(M.pearson([1, 2, null, 4], [2, 4, 9, 8]) - 1) < 1e-9);
});

test("위치별 감지: 감지 시각에 트랩이 있던 위치로 집계", () => {
  const hist = [
    { trap_id: "A", location_id: "L1", start_at: "2026-05-01T00:00:00+09:00", end_at: "2026-05-05T00:00:00+09:00" },
    { trap_id: "A", location_id: "L2", start_at: "2026-05-05T00:00:00+09:00", end_at: null },
  ];
  const ev = [
    { trap_id: "A", detected_at: "2026-05-04T10:00:00+09:00" },
    { trap_id: "A", detected_at: "2026-05-06T10:00:00+09:00" },
    { trap_id: "A", detected_at: "2026-05-05T00:00:00+09:00" },
  ];
  assert.deepEqual(M.locationCounts(ev, hist), { L1: 1, L2: 2 });
});

test("eCO₂ 판정·최근 시각 표기·CSV", () => {
  assert.equal(M.ecoJudge(1000, 1000), "collect");
  assert.equal(M.ecoJudge(999, 1000), "ok");
  assert.equal(M.ecoJudge(null, 1000), null);
  assert.equal(M.fmtRecent("2026-05-10T09:05:00+09:00", NOW), "09:05");
  assert.equal(M.fmtRecent("2026-05-08T09:05:00+09:00", NOW), "05-08 09:05");
  assert.equal(M.fmtRecent(null, NOW), "—");
  assert.equal(M.toCsv(["a", "b"], [[1, null], ['x,"y"', 2]]), 'a,b\r\n1,\r\n"x,""y""",2');
});
