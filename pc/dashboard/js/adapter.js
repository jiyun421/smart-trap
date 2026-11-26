/* Pi 백엔드(backend/docs/api.md) 응답을 대시보드가 쓰는 형태로 바꾼다 (DOM 없음, node로 테스트 가능).
 * 백엔드에 없는 값은 0이 아니라 null로 둔다(화면에서 "—"). 센서 대응:
 *   로드셀(load_cell_g) ← env.bait_g,  eCO₂·TVOC ← 백엔드에 없음(null)
 * 추천 변환은 pc/src/backend_client.py 의 from_backend_runs 와 같은 규칙이다. */
(function (root) {
  "use strict";

  var DECISIONS = {
    recommended: 1,
    keep: 1,
    device_check: 1,
    insufficient_data: 1,
  };

  function num(v) {
    return typeof v === "number" ? v : null;
  }

  /** 백엔드의 UTC 시각(...Z)을 KST(+09:00) 문자열로 바꾼다. 시간대별 집계가 문자열의 시·날짜를 그대로 읽기 때문이다. */
  function kst(t) {
    var ms = t ? Date.parse(t) : NaN;
    return isNaN(ms)
      ? null
      : new Date(ms + 9 * 3600 * 1000).toISOString().slice(0, 19) + "+09:00";
  }

  /** /api/traps 항목 + /api/traps/<id>/status → 트랩 한 행 */
  function trapRow(trap, status) {
    var state = status && status.connection_state;
    var door = status && status.observations && status.observations.door_state;
    return {
      trap_id: trap.trap_id,
      location_id: trap.location_id || null,
      installed_at: kst(trap.started_at),
      status: state === "online" ? "operating" : state || "unknown",
      door_state: door && !door.stale ? door.value : null,
      last_seen_at: status ? kst(status.last_received_at) : null,
    };
  }

  /** /api/readings 항목 → 센서 측정 행 */
  function readingRow(e) {
    var env = e.env || {};
    return {
      trap_id: e.trap_id,
      measured_at: kst(e.observed_at),
      temperature_c: num(env.temperature_c),
      humidity_pct: num(env.humidity_pct),
      tvoc_ppb: null,
      eco2_ppm: null,
      load_cell_g: num(env.bait_g),
    };
  }

  /** /api/visits 항목 → 감지 이벤트 행. 종이 아직 정해지지 않았거나 unknown이면 classification은 null(미식별) */
  function eventRow(v) {
    var entry = v.entry,
      res = v.resolution;
    var species = res ? res.species_code : null;
    var conf =
      res && num(res.confidence) !== null
        ? res.confidence
        : entry
          ? num(entry.confidence)
          : null;
    return {
      event_id: v.visit_id,
      trap_id: v.trap_id,
      detected_at: kst(entry ? entry.observed_at : v.observed_at),
      ir_detected: !!entry,
      classification:
        !species || species === "unknown"
          ? null
          : species === "rat"
            ? "rat"
            : "non_rat",
      confidence: conf,
    };
  }

  /** 설치 이력 → 위치 이력 행 */
  function historyRow(d) {
    return {
      trap_id: d.trap_id,
      location_id: d.location_id,
      start_at: kst(d.started_at),
      end_at: kst(d.ended_at),
    };
  }

  /** 설치된 적 없는 위치를 후보로 본다. 지도 좌표(x, y)는 백엔드에 없어 null이다. */
  function locationRows(locations, deployments) {
    var used = {};
    deployments.forEach(function (d) {
      used[d.location_id] = true;
    });
    return locations.map(function (l) {
      return {
        location_id: l.location_id,
        name: l.name,
        is_candidate: !used[l.location_id],
        x: null,
        y: null,
      };
    });
  }

  /** 같은 실행(batch_id)의 추천 run들 → 추천 화면 형식. PC가 보낸 run(details.decision)만 대상이다. */
  function recommendations(runs) {
    var mine = runs.filter(function (r) {
      return r.details && r.details.batch_id && DECISIONS[r.details.decision];
    });
    if (!mine.length) return null;
    var newest = mine.reduce(function (a, b) {
      return b.generated_at > a.generated_at ? b : a;
    });
    var batch = mine
      .filter(function (r) {
        return r.details.batch_id === newest.details.batch_id;
      })
      .sort(function (a, b) {
        return a.details.index - b.details.index;
      });
    var first = batch[0];
    return {
      run_id: first.details.batch_id,
      generated_at: kst(first.generated_at),
      analysis_period: { from: kst(first.data_from), to: kst(first.data_to) },
      algorithm_version: first.model_version,
      data_basis: first.data_basis,
      recommendations: batch.map(function (run) {
        var d = run.details,
          top = d.decision === "recommended" ? run.candidates[0] : null;
        return {
          trap_id: run.trap_id,
          current_location_id: d.current_location_id,
          recommended_location_id: top ? top.location_id : null,
          recommended_location_type: d.recommended_location_type,
          relocate: d.relocate,
          status: d.decision,
          priority: d.priority,
          score: top ? top.score : null,
          current_location_score: d.current_location_score,
          reasons: d.reasons,
          actual_stats: d.actual_stats,
          simulated_stats: d.simulated_stats,
        };
      }),
    };
  }

  /** raw: { traps, statuses{trap_id: status}, locations, deployments, readings, visits, runs } (모두 items 배열) */
  function build(raw) {
    return {
      traps: raw.traps.map(function (t) {
        return trapRow(t, raw.statuses[t.trap_id]);
      }),
      locations: locationRows(raw.locations, raw.deployments),
      history: raw.deployments.map(historyRow),
      readings: raw.readings.map(readingRow),
      events: raw.visits.map(eventRow),
      recs: recommendations(raw.runs),
    };
  }

  var api = {
    build: build,
    trapRow: trapRow,
    readingRow: readingRow,
    eventRow: eventRow,
    recommendations: recommendations,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.DashAdapter = api;
})(typeof window !== "undefined" ? window : globalThis);
