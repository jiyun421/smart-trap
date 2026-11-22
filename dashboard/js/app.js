/* 대시보드 화면 구성. 서버에서 온 문자열은 textContent로만 넣는다(HTML로 해석하지 않음). */
(function () {
  "use strict";
  var M = window.DashModel, C = window.DashCharts, cfg = window.DASHBOARD_CONFIG;
  var lastData = null;

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function add(parent) {
    for (var i = 1; i < arguments.length; i++) parent.appendChild(arguments[i]);
    return parent;
  }

  function showError(msg, hint) {
    var box = $("status-msg");
    box.className = "status-msg error";
    box.textContent = msg;
    if (hint) { box.appendChild(document.createElement("br")); box.appendChild(hint); }
    box.hidden = false;
    $("content").hidden = true;
  }

  function serveHint() {
    var s = el("span", null, "");
    s.appendChild(document.createTextNode("파일을 직접 열면(file://) 데이터를 읽을 수 없습니다. 프로젝트 폴더에서 "));
    s.appendChild(el("code", null, "python -m http.server 8000"));
    s.appendChild(document.createTextNode(" 실행 후 http://localhost:8000/dashboard/ 로 접속하세요."));
    return s;
  }

  function dataUrl() {
    return cfg.apiBase ? cfg.apiBase.replace(/\/$/, "") + "/recommendations" : cfg.sampleUrl;
  }

  function load() {
    var url = dataUrl();
    return fetch(url, { headers: { Accept: "application/json" } })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status + " (" + url + ")");
        return res.json();
      })
      .then(function (data) {
        if (!data || !Array.isArray(data.recommendations)) throw new Error("추천 결과 형식이 아닙니다 (recommendations 배열 없음)");
        return data;
      });
  }

  // ------------------------------------------------------------ 화면 조각
  function renderBanner(basis) {
    var b = $("sim-banner"), info = M.basisInfo(basis);
    b.hidden = !info.simulated;
    b.textContent = "";
    if (info.simulated) add(b, el("strong", null, "시뮬레이션 기반"), document.createTextNode(info.note));
  }

  function renderMeta(d, from) {
    $("meta").textContent = "실행 " + d.run_id + " · 생성 " + M.fmtDateTime(d.generated_at) + " · 분석 기간 " +
      M.periodLabel(d.analysis_period) + " · 알고리즘 " + (d.algorithm_version || "—") + " · 데이터: " + from;
  }

  function badge(r) {
    var m = M.statusMeta(r.status);
    var cls = M.STATUS[r.status] ? "s-" + r.status : "s-unknown";
    var b = el("span", "badge " + cls);
    add(b, el("span", "icon", m.icon), document.createTextNode(m.label + (r.status === "recommended" && r.priority ? " · 우선순위 " + r.priority : "")));
    b.firstChild.setAttribute("aria-hidden", "true");
    return b;
  }

  function renderKpis(recs) {
    var counts = M.countByStatus(recs), box = $("kpis");
    box.textContent = "";
    ["recommended", "device_check", "insufficient_data", "keep"].forEach(function (s) {
      var k = el("div", "kpi"), n = el("div", "num", String(counts[s]));
      n.appendChild(el("small", null, "/ " + recs.length + "대"));
      add(k, badge({ status: s }), n);
      box.appendChild(k);
    });
  }

  function statGroup(title, pairs) {
    var g = el("div", "stat-group"), dl = el("dl");
    add(g, el("h4", null, title));
    pairs.forEach(function (p) { add(dl, add(el("div"), el("dt", null, p[0]), el("dd", null, p[1]))); });
    return add(g, dl);
  }

  function renderCards(recs, basis) {
    var box = $("cards");
    box.textContent = "";
    M.sortRecommendations(recs).forEach(function (r) {
      var a = r.actual_stats || {}, s = r.simulated_stats || {};
      var card = el("article", "card");
      add(card, add(el("header"), el("h3", null, r.trap_id), badge(r)));

      var route = el("p", "route");
      if (r.relocate && r.recommended_location_id) {
        add(route, document.createTextNode(r.current_location_id), el("span", "arrow", "→"), document.createTextNode(r.recommended_location_id));
      } else {
        route.textContent = "현재 위치 " + r.current_location_id;
      }
      card.appendChild(route);

      if (r.relocate) {
        card.appendChild(el("p", "score-line", "위치 점수 " + M.fmtNum(r.current_location_score, 2) + " → " + M.fmtNum(r.score, 2) + " (상대값, 최고=1.00)"));
      } else if (r.status !== "device_check" && r.current_location_score !== null && r.current_location_score !== undefined) {
        card.appendChild(el("p", "score-line", "현재 위치 점수 " + M.fmtNum(r.current_location_score, 2) + " (상대값, 최고=1.00)"));
      }

      var ul = el("ul", "reasons");
      (r.reasons || []).forEach(function (t) { ul.appendChild(el("li", null, t)); });
      card.appendChild(ul);

      card.appendChild(statGroup(M.detectionLabel(basis), [
        ["작동 시간", M.fmtNum(a.operating_hours, 1) + (a.operating_hours == null ? "" : "h")],
        ["쥐 감지", M.fmtCount(a.rat_detections) + (a.rat_detections == null ? "" : "건")],
        ["시간당 감지", M.fmtNum(a.rat_detections_per_hour, 3)],
      ]));
      card.appendChild(statGroup("가상 포획 (시뮬레이션 추정)", [
        ["가상 포획", M.fmtCount(s.captures) + (s.captures == null ? "" : "건")],
        ["전환율", M.fmtPct(s.capture_conversion_rate)],
        ["시간당 포획", M.fmtNum(s.captures_per_hour, 3)],
      ]));
      box.appendChild(card);
    });
  }

  function renderCharts(recs) {
    C.destroyAll();
    var sorted = M.sortRecommendations(recs);
    var rate = M.chartRows(recs, function (r) { return (r.actual_stats || {}).rat_detections_per_hour; });
    var conv = M.chartRows(recs, function (r) { return (r.simulated_stats || {}).capture_conversion_rate; });
    C.singleBar($("chart-rate"), rate, function (v) { return M.fmtNum(v, 3); }, sorted.map(function (r) {
      var a = r.actual_stats || {};
      return "쥐 감지 " + M.fmtCount(a.rat_detections) + "건 / 작동 " + M.fmtNum(a.operating_hours, 1) + "시간";
    }));
    C.singleBar($("chart-conv"), conv, function (v) { return M.fmtPct(v); }, sorted.map(function (r) {
      var a = r.actual_stats || {}, s = r.simulated_stats || {};
      return "가상 포획 " + M.fmtCount(s.captures) + "건 / 쥐 감지 " + M.fmtCount(a.rat_detections) + "건";
    }));

    var recd = sorted.filter(function (r) { return r.status === "recommended"; });
    var box = $("box-score"), frame = box.querySelector(".chart-frame"), old = box.querySelector(".empty-chart");
    if (old) old.remove();
    frame.hidden = recd.length === 0;
    if (recd.length === 0) {
      box.appendChild(el("p", "empty-chart", "이번 분석에서는 재배치를 권고한 트랩이 없습니다."));
    } else {
      C.scoreCompare($("chart-score"),
        recd.map(function (r) { return r.trap_id; }),
        recd.map(function (r) { return r.current_location_score; }),
        recd.map(function (r) { return r.score; }));
    }
  }

  function renderTable(recs) {
    var t = $("table");
    t.textContent = "";
    var head = ["트랩", "현재 위치", "판정", "작동 시간(h)", "쥐 감지(건)", "시간당 감지", "가상 포획(건)", "전환율", "현재 점수", "추천 점수"];
    var tr = el("tr");
    head.forEach(function (h) { tr.appendChild(el("th", null, h)); });
    t.appendChild(add(el("thead"), tr));
    var body = el("tbody");
    M.sortRecommendations(recs).forEach(function (r) {
      var a = r.actual_stats || {}, s = r.simulated_stats || {};
      var row = el("tr");
      [r.trap_id, r.current_location_id, M.statusMeta(r.status).label, M.fmtNum(a.operating_hours, 1), M.fmtCount(a.rat_detections),
        M.fmtNum(a.rat_detections_per_hour, 3), M.fmtCount(s.captures), M.fmtPct(s.capture_conversion_rate),
        M.fmtNum(r.current_location_score, 2), M.fmtNum(r.score, 2)].forEach(function (v) { row.appendChild(el("td", null, v)); });
      body.appendChild(row);
    });
    t.appendChild(body);
  }

  function renderNotes(basis) {
    var ul = $("notes");
    ul.textContent = "";
    [
      "위치 점수는 이번 분석에서 관측된 위치들 사이의 상대값입니다(최고 위치=1.00). 절대적인 포획 성능이 아닙니다.",
      "‘장치 점검’ 트랩은 같은 위치의 다른 트랩보다 전환율이 확실히 낮아 위치가 아니라 장치 문제로 판단한 것입니다. 이 트랩은 옮겨도 소용이 없고, 위치 점수 계산에서도 제외했습니다.",
      "‘데이터 부족’은 관측 7일 미만, 작동 72시간 미만, 쥐 감지 10건 미만 중 하나입니다. 막대는 빗금으로 표시하며 추천을 확정하지 않습니다.",
      "‘—’ 는 계산 불가(분모 0 또는 결측)이며 0이 아닙니다.",
      "설치 이력이 없는 후보 위치는 성과를 예측할 수 없어 추천하지 않습니다.",
    ].forEach(function (t) { ul.appendChild(el("li", null, t)); });
    $("source-note").textContent = "출처: " + M.basisInfo(basis).note;
  }

  function render(d, from) {
    lastData = { d: d, from: from };
    var recs = d.recommendations;
    renderBanner(d.data_basis);
    renderMeta(d, from);
    $("status-msg").hidden = true;
    $("content").hidden = false;
    if (recs.length === 0) {
      $("content").hidden = true;
      var m = $("status-msg");
      m.className = "status-msg"; m.textContent = "이번 실행에는 추천 결과가 없습니다."; m.hidden = false;
      return;
    }
    renderKpis(recs);
    renderCards(recs, d.data_basis);
    renderCharts(recs);
    renderTable(recs);
    renderNotes(d.data_basis);
  }

  load().then(function (d) { render(d, cfg.apiBase ? "API" : "샘플 파일"); })
    .catch(function (e) { showError("데이터를 불러오지 못했습니다: " + e.message, serveHint()); });

  // 다크/라이트 전환 시 차트 색 갱신
  if (window.matchMedia) {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
      if (lastData) renderCharts(lastData.d.recommendations);
    });
  }
})();
