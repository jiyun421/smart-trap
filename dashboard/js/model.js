/* 대시보드 순수 로직 (DOM 없음, node로 테스트 가능).
 * 결측(null)은 0이 아니라 "—"로 표시한다. 계산 불가를 0 성과로 오해하지 않기 위함이다. */
(function (root) {
  "use strict";

  // 판정 상태: 아이콘 + 라벨을 항상 함께 쓴다(색만으로 구분하지 않음). order는 정렬 우선순위.
  var STATUS = {
    recommended: { label: "재배치 권고", icon: "⇄", order: 1 },
    device_check: { label: "장치 점검", icon: "!", order: 2 },
    insufficient_data: { label: "데이터 부족", icon: "…", order: 3 },
    keep: { label: "유지", icon: "✓", order: 4 },
  };
  var UNKNOWN_STATUS = { label: "알 수 없음", icon: "?", order: 9 };

  function statusMeta(status) {
    return STATUS[status] || UNKNOWN_STATUS;
  }

  /** 재배치 권고는 priority 순, 나머지는 상태 순서 → 트랩 ID 순. 원본 배열은 바꾸지 않는다. */
  function sortRecommendations(recs) {
    return recs.slice().sort(function (a, b) {
      var d = statusMeta(a.status).order - statusMeta(b.status).order;
      if (d !== 0) return d;
      if (a.status === "recommended")
        return (a.priority || 99) - (b.priority || 99);
      return String(a.trap_id).localeCompare(String(b.trap_id));
    });
  }

  function countByStatus(recs) {
    var counts = {
      recommended: 0,
      device_check: 0,
      insufficient_data: 0,
      keep: 0,
    };
    recs.forEach(function (r) {
      if (r.status in counts) counts[r.status] += 1;
    });
    return counts;
  }

  function isNum(v) {
    return typeof v === "number" && isFinite(v);
  }
  function fmtNum(v, digits) {
    return isNum(v) ? v.toFixed(digits === undefined ? 3 : digits) : "—";
  }
  function fmtPct(v) {
    return isNum(v) ? (v * 100).toFixed(1) + "%" : "—";
  }
  function fmtCount(v) {
    return isNum(v) ? String(v) : "—";
  }

  /** "2026-11-23T14:05:30+09:00" → "2026-11-23 14:05" (타임존 변환 없이 문자열 그대로 사용) */
  function fmtDateTime(iso) {
    var m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(iso || ""));
    return m ? m[1] + " " + m[2] : "—";
  }

  function _utcDay(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
    return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : null;
  }
  function _ymd(ms) {
    return new Date(ms).toISOString().slice(0, 10);
  }

  /** analysis_period의 to는 배타적(다음 날 0시)이므로 표시할 때 마지막 날은 하루 전. */
  function periodLabel(period) {
    var from = period && _utcDay(period.from);
    var to = period && _utcDay(period.to);
    if (from === null || to === null || to <= from) return "—";
    var days = Math.round((to - from) / 86400000);
    return _ymd(from) + " ~ " + _ymd(to - 86400000) + " (" + days + "일)";
  }

  /** 시뮬레이션 표시 여부. 필드가 없거나 불명확하면 안전하게 시뮬레이션 기반으로 본다. */
  function basisInfo(basis) {
    var simulated = !basis || basis.is_simulation_based !== false;
    var note =
      (basis && basis.note) ||
      "포획 관련 수치는 가상 데이터 기반 추정이며 실제 포획 실적이 아님";
    return { simulated: simulated, note: note };
  }

  /** 감지 통계 묶음의 제목. 실제/가상 감지를 구분해 표시한다(출처를 모르면 "감지 데이터"). */
  function detectionLabel(basis) {
    var src = basis && basis.detection_data;
    if (src === "actual") return "실제 감지 데이터";
    if (src === "synthetic") return "가상 감지 데이터";
    if (src === "mixed") return "감지 데이터 (실제+가상 혼합)";
    return "감지 데이터";
  }

  /** 차트용 행: 트랩 라벨 + 값(결측은 null 그대로) + 데이터 부족 여부 */
  function chartRows(recs, pick) {
    return sortRecommendations(recs).map(function (r) {
      return {
        label: r.trap_id + " @" + r.current_location_id,
        status: r.status,
        value: pick(r),
        insufficient: r.status === "insufficient_data",
      };
    });
  }


  // ------------------------------------------------------------ 화면용 계산
  // 프로젝트의 모든 시각은 KST(+09:00)다. 날짜 구분은 KST 기준으로 한다.
  var KST_MS = 9 * 3600 * 1000, DAY_MS = 86400000, OFFLINE_MS = 30 * 60 * 1000;

  function ms(iso) {
    var t = Date.parse(iso);
    return isFinite(t) ? t : null;
  }
  function kstDate(t) {
    return new Date(t + KST_MS).toISOString().slice(0, 10);
  }

  var TRAP_STATE = {
    ok: { label: "정상", icon: "●" },
    warn: { label: "점검 필요", icon: "!" },
    off: { label: "오프라인", icon: "○" },
  };

  /** 오프라인: 마지막 통신이 없거나 30분 넘음 / 점검 필요: 상태가 operating이 아니거나 추천 판정이 device_check */
  function trapState(trap, nowMs, rec) {
    var seen = ms(trap.last_seen_at);
    if (seen === null || nowMs - seen > OFFLINE_MS) return "off";
    if (trap.status !== "operating" || (rec && rec.status === "device_check")) return "warn";
    return "ok";
  }

  /** id별 가장 최근 행 (ts 기준) */
  function latestBy(rows, idKey, tsKey) {
    var out = {};
    rows.forEach(function (r) {
      var t = ms(r[tsKey]);
      if (t === null) return;
      var cur = out[r[idKey]];
      if (!cur || t >= ms(cur[tsKey])) out[r[idKey]] = r;
    });
    return out;
  }

  /** [fromMs, toMs) 구간의 행 */
  function inWindow(rows, tsKey, fromMs, toMs) {
    return rows.filter(function (r) {
      var t = ms(r[tsKey]);
      return t !== null && t >= fromMs && t < toMs;
    });
  }

  /** 시각(0~23)별 건수. 분류 결측(미식별)은 호출 쪽에서 걸러서 넘긴다. */
  function hourOfDay(events) {
    var out = [];
    for (var i = 0; i < 24; i++) out.push(0);
    events.forEach(function (e) {
      var m = /T(\d{2}):/.exec(String(e.detected_at || ""));
      if (m) out[+m[1]] += 1;
    });
    return out;
  }

  /** 마지막 days일(now 직전까지)의 날짜별 건수 */
  function dailyCounts(events, nowMs, days) {
    var out = [];
    for (var i = days - 1; i >= 0; i--) out.push({ date: kstDate(nowMs - 1 - i * DAY_MS), count: 0 });
    events.forEach(function (e) {
      var t = ms(e.detected_at);
      if (t === null) return;
      var d = kstDate(t);
      out.forEach(function (o) { if (o.date === d) o.count += 1; });
    });
    return out;
  }

  /** 날짜별 평균(결측 제외). 값이 하나도 없으면 null (0이 아님) */
  function dailyAvg(readings, key, dates) {
    return dates.map(function (d) {
      var vals = readings.filter(function (r) {
        return isNum(r[key]) && String(r.measured_at).slice(0, 10) === d;
      }).map(function (r) { return r[key]; });
      return vals.length ? vals.reduce(function (a, b) { return a + b; }, 0) / vals.length : null;
    });
  }

  /** 피어슨 상관계수. 짝이 3개 미만이거나 분산이 0이면 null */
  function pearson(xs, ys) {
    var px = [], py = [];
    xs.forEach(function (x, i) { if (isNum(x) && isNum(ys[i])) { px.push(x); py.push(ys[i]); } });
    var n = px.length;
    if (n < 3) return null;
    var mx = px.reduce(function (a, b) { return a + b; }, 0) / n;
    var my = py.reduce(function (a, b) { return a + b; }, 0) / n;
    var sxy = 0, sxx = 0, syy = 0;
    for (var i = 0; i < n; i++) {
      sxy += (px[i] - mx) * (py[i] - my); sxx += (px[i] - mx) * (px[i] - mx); syy += (py[i] - my) * (py[i] - my);
    }
    return sxx === 0 || syy === 0 ? null : sxy / Math.sqrt(sxx * syy);
  }

  /** 감지 시각에 트랩이 있던 위치별 건수 (trap_location_history 기준) */
  function locationCounts(events, history) {
    var out = {};
    events.forEach(function (e) {
      var t = ms(e.detected_at);
      if (t === null) return;
      for (var i = 0; i < history.length; i++) {
        var h = history[i], s = ms(h.start_at), en = h.end_at ? ms(h.end_at) : null;
        if (h.trap_id === e.trap_id && s !== null && t >= s && (en === null || t < en)) {
          out[h.location_id] = (out[h.location_id] || 0) + 1;
          break;
        }
      }
    });
    return out;
  }

  /** 오늘(now 직전 날짜)이면 시각만, 아니면 월-일 시각 */
  function fmtRecent(iso, nowMs) {
    var t = ms(iso);
    if (t === null) return "—";
    var s = String(iso);
    return kstDate(t) === kstDate(nowMs - 1) ? s.slice(11, 16) : s.slice(5, 10) + " " + s.slice(11, 16);
  }

  /** eCO₂ 판정. 값이 없으면 판정하지 않는다(null). */
  function ecoJudge(ppm, threshold) {
    if (!isNum(ppm)) return null;
    return ppm >= threshold ? "collect" : "ok";
  }

  function toCsv(header, rows) {
    function q(v) {
      var s = v === null || v === undefined ? "" : String(v);
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    }
    return [header].concat(rows).map(function (r) { return r.map(q).join(","); }).join("\r\n");
  }

  function fmtInt(v) {
    return isNum(v) ? Math.round(v).toLocaleString("en-US") : "—";
  }


  /** 트랩별 화면용 묶음: 위치·추천 판정·최신 측정값·마지막 감지·작동 상태 */
  function trapViews(ctx) {
    var locs = {}, recs = {};
    ctx.locations.forEach(function (l) { locs[l.location_id] = l; });
    ((ctx.recs && ctx.recs.recommendations) || []).forEach(function (r) { recs[r.trap_id] = r; });
    var read = latestBy(ctx.readings, "trap_id", "measured_at");
    var last = latestBy(ctx.events, "trap_id", "detected_at");
    return ctx.traps.map(function (t) {
      return { trap: t, loc: locs[t.location_id] || null, rec: recs[t.trap_id] || null,
        reading: read[t.trap_id] || null, lastEvent: last[t.trap_id] || null,
        state: trapState(t, ctx.now, recs[t.trap_id]) };
    });
  }

  var api = {
    STATUS: STATUS,
    statusMeta: statusMeta,
    sortRecommendations: sortRecommendations,
    countByStatus: countByStatus,
    fmtNum: fmtNum,
    fmtPct: fmtPct,
    fmtCount: fmtCount,
    fmtDateTime: fmtDateTime,
    periodLabel: periodLabel,
    basisInfo: basisInfo,
    detectionLabel: detectionLabel,
    chartRows: chartRows,
    ms: ms, kstDate: kstDate, TRAP_STATE: TRAP_STATE, trapState: trapState, latestBy: latestBy,
    inWindow: inWindow, hourOfDay: hourOfDay, dailyCounts: dailyCounts, dailyAvg: dailyAvg,
    pearson: pearson, locationCounts: locationCounts, fmtRecent: fmtRecent, ecoJudge: ecoJudge,
    toCsv: toCsv, fmtInt: fmtInt, trapViews: trapViews,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.DashModel = api;
})(typeof window !== "undefined" ? window : globalThis);
