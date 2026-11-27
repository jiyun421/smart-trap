// 실제 백엔드(backend/)에서 받은 응답(fixtures/backend)으로 어댑터를 검사한다.
const test = require("node:test");
const assert = require("node:assert/strict");
const A = require("../js/adapter.js");
const fx = (n) => require("./fixtures/backend/" + n + ".json");

test("트랩: 시각은 KST, 결측 문 상태는 null", () => {
  const trap = fx("traps").items[0];
  const row = A.trapRow(trap, fx("traps_TRAP-01_status"));
  assert.equal(row.trap_id, "TRAP-01");
  assert.match(row.installed_at, /\+09:00$/);
  assert.match(row.last_seen_at, /\+09:00$/);
  assert.equal(A.trapRow(trap, null).last_seen_at, null);
});

test("측정값: eCO2/TVOC는 0이 아니라 null", () => {
  const row = A.readingRow(fx("readings_limit_500").items[0]);
  assert.equal(row.tvoc_ppb, null);
  assert.equal(row.eco2_ppm, null);
  assert.equal(typeof row.load_cell_g, "number");
});

test("측정값: 백엔드의 eCO2/TVOC를 옮긴다(0도 값이다)", () => {
  const row = A.readingRow({ trap_id: "TRAP-01", observed_at: "2026-11-27T00:00:00Z", env: { eco2_ppm: 450, tvoc_ppb: 0 } });
  assert.deepEqual([row.eco2_ppm, row.tvoc_ppb], [450, 0]);
});

test("감지: 종 미정·unknown은 null, rat 외는 non_rat", () => {
  const rows = fx("visits_limit_500").items.map(A.eventRow);
  const by = Object.fromEntries(rows.map((r) => [r.event_id, r]));
  assert.equal(by.v1.classification, "rat");
  assert.equal(by.v2.classification, "non_rat");
  assert.equal(by.v3.classification, null);
  assert.equal(by.v4.classification, null);
  assert.ok(rows.every((r) => r.ir_detected));
});

test("추천: 마지막 배치만, 판정·점수 복원, 가상 표시 유지", () => {
  const r = A.recommendations(fx("recommendations_limit_500").items);
  assert.equal(r.run_id, "RUN-E2E-1");
  assert.equal(r.data_basis.is_simulation_based, true);
  const byTrap = Object.fromEntries(r.recommendations.map((x) => [x.trap_id, x]));
  assert.equal(byTrap["TRAP-01"].status, "keep");
  assert.equal(byTrap["TRAP-01"].recommended_location_id, null);
  assert.equal(byTrap["TRAP-02"].status, "recommended");
  assert.equal(typeof byTrap["TRAP-02"].score, "number");
  assert.equal(A.recommendations([]), null);
});

test("지도 좌표는 layout 설정에서, 가상 트랩은 realTrapIds 밖의 트랩", () => {
  const traps = fx("traps").items;
  const locations = fx("locations").items;
  const base = { traps, statuses: {}, locations, deployments: fx("deployments").items, readings: [], visits: [], runs: [] };
  const plain = A.build(base);
  assert.ok(plain.locations.every((l) => l.x === null && l.y === null));
  assert.ok(plain.traps.every((t) => t.is_virtual === false));

  const id = locations[0].location_id;
  const ctx = A.build({ ...base, layout: { [id]: { x: 2, y: 3 } }, realTrapIds: ["TRAP-01"] });
  const loc = ctx.locations.find((l) => l.location_id === id);
  assert.deepEqual([loc.x, loc.y], [2, 3]);
  assert.equal(ctx.traps.find((t) => t.trap_id === "TRAP-01").is_virtual, false);
  assert.ok(ctx.traps.filter((t) => t.trap_id !== "TRAP-01").every((t) => t.is_virtual));
});
