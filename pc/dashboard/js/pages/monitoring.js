/* 02 트랩 모니터링 */
(function () {
  "use strict";
  var M = DashModel,
    U = Dash,
    el = U.el,
    add = U.add;
  var filter = "all",
    query = "";

  function row(label, value, note) {
    var r = el("div", "kv");
    add(r, el("span", "k", label), el("span", "v", value));
    if (note) r.lastChild.appendChild(el("span", "v-note", " " + note));
    return r;
  }

  Dash.mount("monitoring", function (ctx, main) {
    var views = M.trapViews(ctx),
      thr = ctx.settings.eco2Threshold,
      now = ctx.now;
    var cnt = { all: views.length, ok: 0, warn: 0, off: 0 };
    views.forEach(function (v) {
      cnt[v.state] += 1;
    });

    main.appendChild(
      U.pageHead(
        "트랩 모니터링",
        "트랩별 센서 상태와 최근 감지 · 총 " + views.length + "대",
      ),
    );

    var bar = el("div", "filter-bar"),
      tabs = el("div", "seg");
    var list = el("div", "trap-grid");

    function paint() {
      list.textContent = "";
      var q = query.trim().toLowerCase();
      var shown = views.filter(function (v) {
        var name = (v.loc ? v.loc.name : "") + " " + v.trap.trap_id;
        return (
          (filter === "all" || v.state === filter) &&
          (!q || name.toLowerCase().indexOf(q) >= 0)
        );
      });
      if (!shown.length)
        list.appendChild(el("p", "muted", "조건에 맞는 트랩이 없습니다."));
      shown.forEach(function (v) {
        var r = v.reading,
          ev = v.lastEvent;
        var card = el("article", "trap-card st-border-" + v.state),
          head = el("header");
        var title = el("div");
        add(
          title,
          el("h3", null, v.trap.trap_id + (v.trap.is_virtual ? " · 가상" : "")),
          el("span", "muted", v.loc ? v.loc.name : v.trap.location_id),
        );
        add(card, add(head, title, U.stateBadge(v.state)));
        var env = r
          ? M.fmtNum(r.temperature_c, 1) +
            "℃ / " +
            M.fmtNum(r.humidity_pct, 0) +
            "%"
          : "—";
        var eco = r ? M.ecoJudge(r.eco2_ppm, thr) : null;
        var door =
          v.trap.door_state === "open"
            ? "열림"
            : v.trap.door_state === "closed"
              ? "닫힘"
              : "—";
        var ai = !ev
          ? "—"
          : ev.classification === "rat"
            ? "목표종(쥐)"
            : ev.classification === "non_rat"
              ? "비목표종"
              : "미식별";
        var load =
          r && typeof r.load_cell_g === "number"
            ? M.fmtNum(r.load_cell_g, 1) + "g"
            : "—";
        add(
          card,
          row("온도 / 습도", env),
          row("미끼 무게", load),
          row("도어", door),
          row(
            "eCO₂",
            r ? M.fmtInt(r.eco2_ppm) + "ppm" : "—",
            eco === "collect" ? "· 참고값 · 수거 권장" : "· 참고값",
          ),
          row(
            "TVOC",
            r && typeof r.tvoc_ppb === "number"
              ? M.fmtInt(r.tvoc_ppb) + "ppb"
              : "—",
            "· 참고값",
          ),
          row(
            "최근 AI 식별",
            ai,
            ev && typeof ev.confidence === "number"
              ? "· 신뢰도 " + M.fmtNum(ev.confidence, 2)
              : "",
          ),
          row("최근 감지", ev ? M.fmtRecent(ev.detected_at, now) : "—"),
          row(
            "마지막 통신",
            v.trap.last_seen_at ? M.fmtRecent(v.trap.last_seen_at, now) : "—",
          ),
        );
        if (v.state === "off" && v.trap.last_seen_at)
          card.appendChild(
            el(
              "p",
              "muted",
              "마지막 통신이 35분 넘게 없어 센서 값은 마지막 수신값입니다.",
            ),
          );
        list.appendChild(card);
      });
    }

    [
      ["all", "전체"],
      ["ok", "정상"],
      ["warn", "점검 필요"],
      ["off", "오프라인"],
    ].forEach(function (o) {
      var b = el(
        "button",
        "seg-btn" + (filter === o[0] ? " on" : ""),
        o[1] + " " + cnt[o[0]],
      );
      b.type = "button";
      b.setAttribute("aria-pressed", filter === o[0] ? "true" : "false");
      b.onclick = function () {
        filter = o[0];
        Array.prototype.forEach.call(tabs.children, function (c) {
          c.classList.remove("on");
          c.setAttribute("aria-pressed", "false");
        });
        b.classList.add("on");
        b.setAttribute("aria-pressed", "true");
        paint();
      };
      tabs.appendChild(b);
    });
    var search = el("input", "search");
    search.type = "search";
    search.value = query;
    search.placeholder = "트랩 ID·위치 검색";
    search.setAttribute("aria-label", "트랩 검색");
    search.oninput = function () {
      query = search.value;
      paint();
    };
    add(bar, tabs, search);
    add(main, bar, list);
    paint();
  });
})();
