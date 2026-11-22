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
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.DashModel = api;
})(typeof window !== "undefined" ? window : globalThis);
