/* 01 종합 현황 */
(function () {
  "use strict";
  var M = DashModel, D = DashData, U = Dash, el = U.el, add = U.add;
  var range = "24h"; // "24h" | "7d"

  Dash.mount("overview", function (ctx, main, redraw) {
    var views = M.trapViews(ctx), st = ctx.settings, now = ctx.now, DAY = 86400000;
    var rat = ctx.events.filter(function (e) { return e.classification === "rat"; });
    var d24 = M.inWindow(rat, "detected_at", now - DAY, now).length;
    var dPrev = M.inWindow(rat, "detected_at", now - 2 * DAY, now - DAY).length;
    var cnt = { ok: 0, warn: 0, off: 0 };
    views.forEach(function (v) { cnt[v.state] += 1; });
    var review = ((ctx.recs && ctx.recs.recommendations) || []).filter(function (r) { return r.status === "recommended"; }).length;

    // 헤더 + 운영 중 목표종
    var species = [];
    views.forEach(function (v) { D.speciesOf(st, v.trap.trap_id).forEach(function (s) { if (species.indexOf(s) < 0) species.push(s); }); });
    var chips = el("div", "chips");
    chips.appendChild(document.createTextNode("운영 중 목표종 "));
    species.forEach(function (s) { chips.appendChild(el("span", "chip", s)); });
    var change = el("a", "chip-link", "변경"); change.href = "settings.html"; chips.appendChild(change);
    main.appendChild(U.pageHead("종합 현황", "설정된 목표종 기준 · 최근 24시간", chips));

    // 요약 지표
    var kp = el("section", "grid-stats"); kp.setAttribute("aria-label", "요약 지표");
    var delta = d24 - dPrev;
    var recLink = el("a", "stat-note link", "추천 위치 확인 →"); recLink.href = "recommend.html";
    add(kp,
      U.stat("전체 트랩", String(views.length), "대", "등록된 트랩"),
      U.stat("정상 작동", String(cnt.ok), "대", "점검 필요 " + cnt.warn + " · 오프라인 " + cnt.off, { tone: "good" }),
      U.stat("목표종 감지", M.fmtInt(d24), "회", "전일 대비 " + (delta >= 0 ? "+" : "") + delta + "회 · " + M.detectionLabel(ctx.recs && ctx.recs.data_basis)),
      U.stat("재배치 검토", String(review), "대", recLink, { tone: "blue" }));
    main.appendChild(kp);

    // 트랩별 상태 + 감지 추이
    var row1 = el("div", "grid-2");
    var all = el("a", "small-link", "전체 보기"); all.href = "monitoring.html";
    var p1 = U.panel("트랩별 상태", null, all);
    p1.appendChild(U.table(["트랩 ID", "설치 위치", "상태", "최근 감지"], views.map(function (v) {
      return [v.trap.trap_id, v.loc ? v.loc.name : v.trap.location_id, U.stateBadge(v.state),
        v.lastEvent ? M.fmtRecent(v.lastEvent.detected_at, now) : "—"];
    })));

    var tabs = el("div", "seg");
    [["24h", "24시간"], ["7d", "7일"]].forEach(function (o) {
      var b = el("button", "seg-btn" + (range === o[0] ? " on" : ""), o[1]); b.type = "button";
      b.setAttribute("aria-pressed", range === o[0] ? "true" : "false");
      b.onclick = function () { range = o[0]; redraw(); };
      tabs.appendChild(b);
    });
    var p2 = U.panel("최근 감지 추이", range === "24h" ? "시간별 목표종 감지" : "일별 목표종 감지", tabs);
    var bars, xl, max, peakText;
    if (range === "24h") {
      var h = M.hourOfDay(M.inWindow(rat, "detected_at", now - DAY, now));
      max = Math.max.apply(null, h.concat([4]));
      bars = h.map(function (v, i) { return { value: v, hl: v === max && v > 0, title: String(i).padStart(2, "0") + "시 · " + v + "회" }; });
      xl = ["00시", "06시", "12시", "18시", "23시"];
      var pk = h.indexOf(Math.max.apply(null, h));
      peakText = Math.max.apply(null, h) > 0 ? "피크: " + pk + "시 (" + h[pk] + "회)" : "감지 없음";
    } else {
      var dc = M.dailyCounts(rat, now, 7);
      max = Math.max.apply(null, dc.map(function (d) { return d.count; }).concat([4]));
      bars = dc.map(function (d) { return { value: d.count, hl: d.count === max, title: d.date + " · " + d.count + "회" }; });
      xl = dc.map(function (d) { return d.date.slice(5); });
      var best = dc.reduce(function (a, b) { return b.count > a.count ? b : a; }, dc[0]);
      peakText = best.count > 0 ? "피크: " + best.date.slice(5) + " (" + best.count + "회)" : "감지 없음";
    }
    max = Math.ceil(max / 4) * 4;
    p2.appendChild(U.barChart(bars, max, 4, { xlabels: xl, gap: range === "24h" ? 4 : 12 }));
    var lg = el("div", "legend");
    add(lg, add(el("span"), el("i", "sw teal"), document.createTextNode("목표종 감지")),
      add(el("span"), el("i", "sw teal-d"), document.createTextNode("피크")), el("span", null, peakText));
    p2.appendChild(lg);
    add(main, add(row1, p1, p2));

    // 알림 / 환경 평균 / eCO2
    var row2 = el("div", "grid-3");
    var p3 = U.panel("최근 알림", "이벤트에서 파생");
    var items = [];
    ctx.events.forEach(function (e) {
      if (e.classification === "rat") items.push({ t: e.detected_at, kind: "감지", cls: "teal", text: e.trap_id + " 목표종(쥐) 식별 · 신뢰도 " + M.fmtNum(e.confidence, 2) });
      else if (e.classification === "non_rat") items.push({ t: e.detected_at, kind: "비목표", cls: "off", text: e.trap_id + " 비목표종 진입" });
    });
    views.forEach(function (v) {
      if (v.reading && M.ecoJudge(v.reading.eco2_ppm, st.eco2Threshold) === "collect")
        items.push({ t: v.reading.measured_at, kind: "수거", cls: "warn", text: v.trap.trap_id + " eCO₂ " + M.fmtInt(v.reading.eco2_ppm) + "ppm → 수거 권장" });
      if (v.rec && v.rec.status === "device_check") items.push({ t: v.reading ? v.reading.measured_at : ctx.serverTime, kind: "점검", cls: "warn", text: v.trap.trap_id + " 장치 점검 권고" });
    });
    if (ctx.recs) items.push({ t: ctx.recs.generated_at, kind: "추천", cls: "blue", text: "재배치 추천 생성 (" + ctx.recs.run_id + ")" });
    items.sort(function (a, b) { return M.ms(b.t) - M.ms(a.t); });
    var list = el("div", "alerts");
    if (!items.length) list.appendChild(el("p", "muted", "표시할 알림이 없습니다."));
    items.slice(0, 5).forEach(function (a) {
      add(list, add(el("div", "alert"), el("span", "tag t-" + a.cls, a.kind), el("span", null, a.text + " · " + M.fmtRecent(a.t, now))));
    });
    p3.appendChild(list);

    var p4 = U.panel("환경 평균", "전체 트랩 최신값");
    function avg(key) {
      var v = views.map(function (x) { return x.reading && x.reading[key]; }).filter(function (x) { return typeof x === "number"; });
      return v.length ? v.reduce(function (a, b) { return a + b; }, 0) / v.length : null;
    }
    var env = el("div", "env");
    add(env, add(el("div", "env-cell"), el("div", "stat-label", "온도"), el("div", "env-val", M.fmtNum(avg("temperature_c"), 1)), el("span", "unit", "℃")),
      add(el("div", "env-cell"), el("div", "stat-label", "습도"), el("div", "env-val", M.fmtNum(avg("humidity_pct"), 0)), el("span", "unit", "%")));
    add(p4, env, el("p", "muted", "온습도 센서 기준 · 트랩별 값은 트랩 모니터링에서 확인"));

    var p5 = U.panel("포획물 부패 확인", "eCO₂");
    p5.appendChild(el("p", "muted", "포획 여부 정보가 없어 전체 트랩의 최신 eCO₂를 표시합니다. 수거 권장 기준 " + M.fmtInt(st.eco2Threshold) + "ppm 이상"));
    var eco = el("div", "eco-list");
    views.forEach(function (v) {
      var j = v.reading ? M.ecoJudge(v.reading.eco2_ppm, st.eco2Threshold) : null;
      var tag = j === "collect" ? el("span", "tag t-warn", "수거 권장") : j === "ok" ? el("span", "tag t-teal", "정상") : el("span", "tag t-off", "측정 없음");
      add(eco, add(el("div", "eco-row"), el("b", null, v.trap.trap_id), el("span", "muted grow", v.reading ? M.fmtInt(v.reading.eco2_ppm) + "ppm" : "—"), tag));
    });
    p5.appendChild(eco);
    add(main, add(row2, p3, p4, p5));
  });
})();
