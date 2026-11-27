/* 공통 틀(사이드바·상단바·시뮬레이션 배너)과 DOM 도우미. 서버에서 온 문자열은 textContent로만 넣는다. */
(function (root) {
  "use strict";
  var M = root.DashModel,
    D = root.DashData,
    cfg = root.DASHBOARD_CONFIG;
  var SVG_NS = "http://www.w3.org/2000/svg";

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function add(parent) {
    for (var i = 1; i < arguments.length; i++)
      if (arguments[i]) parent.appendChild(arguments[i]);
    return parent;
  }
  function svg(paths, size, attrs) {
    var s = document.createElementNS(SVG_NS, "svg");
    s.setAttribute("width", size || 20);
    s.setAttribute("height", size || 20);
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("fill", "none");
    s.setAttribute("stroke", "currentColor");
    s.setAttribute("stroke-width", "1.8");
    s.setAttribute("aria-hidden", "true");
    for (var k in attrs || {}) s.setAttribute(k, attrs[k]);
    paths.forEach(function (d) {
      var p = document.createElementNS(SVG_NS, "path");
      p.setAttribute("d", d);
      s.appendChild(p);
    });
    return s;
  }

  var NAV = [
    [
      "overview",
      "index.html",
      "종합 현황",
      ["M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"],
    ],
    [
      "monitoring",
      "monitoring.html",
      "트랩 모니터링",
      [
        "M6 3h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z",
        "M4 10h16",
        "M12 13a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
      ],
    ],
    [
      "analysis",
      "analysis.html",
      "감지·포획 분석",
      ["M4 20V4", "M4 20h16", "M8 16v-4M12 16V8M16 16v-6"],
    ],
    [
      "recommend",
      "recommend.html",
      "설치 위치 추천",
      [
        "M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z",
        "M12 7a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z",
      ],
    ],
    [
      "external",
      "external.html",
      "외부 데이터 추천",
      ["M3 3h18v18H3z", "M3 9h18M3 15h18M9 3v18M15 3v18"],
    ],
  ];
  var GEAR = [
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
    "M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  ];

  function buildNav(active) {
    var nav = el("nav", "nav"),
      logo = el("div", "logo"),
      name = el("div", "logo-name");
    nav.setAttribute("aria-label", "주 메뉴");
    var mark = svg(["M11 11h10v12H11z", "M11 15h10"], 32, {
      "stroke-width": "1.6",
      viewBox: "0 0 32 32",
    });
    var c = document.createElementNS(SVG_NS, "circle");
    c.setAttribute("cx", 16);
    c.setAttribute("cy", 16);
    c.setAttribute("r", 14);
    mark.insertBefore(c, mark.firstChild);
    var brand = el("span", "brand", "SMART");
    brand.appendChild(el("span", "brand-accent", "TRAP"));
    add(name, brand, el("span", "logo-sub", "모니터링 시스템"));
    add(logo, mark, name);
    var links = el("div", "nav-links");
    NAV.forEach(function (n) {
      var a = el("a", "nav-link" + (n[0] === active ? " active" : ""));
      a.href = n[1];
      if (n[0] === active) a.setAttribute("aria-current", "page");
      add(a, svg(n[3]), document.createTextNode(n[2]));
      links.appendChild(a);
    });
    return add(nav, logo, links);
  }

  function buildTopbar(active) {
    var bar = el("header", "topbar"),
      left = el("div", "conn"),
      right = el("div", "topbar-right");
    var dot = el("span", "dot");
    dot.id = "conn-dot";
    var txt = el("span", null, "불러오는 중…");
    txt.id = "conn-text";
    add(left, dot, txt);
    var src = el(
      "span",
      "src-badge",
      cfg.apiBase ? "Pi API" : "샘플 데이터 (Mock)",
    );
    var gear = el("a", "gear" + (active === "settings" ? " active" : ""));
    gear.href = "settings.html";
    gear.setAttribute("aria-label", "설정");
    gear.title = "설정";
    if (active === "settings") gear.setAttribute("aria-current", "page");
    gear.appendChild(svg(GEAR));
    return add(bar, left, add(right, src, gear));
  }

  function setConn(ok, text) {
    var d = document.getElementById("conn-dot"),
      t = document.getElementById("conn-text");
    d.className = "dot" + (ok ? "" : " bad");
    t.textContent = text;
  }

  /** 가상 포획 표시 배너: data_basis를 모르면 안전하게 시뮬레이션 기반으로 본다. */
  function renderBanner(box, recs) {
    var info = M.basisInfo(recs && recs.data_basis);
    box.hidden = !info.simulated;
    box.textContent = "";
    if (info.simulated)
      add(
        box,
        el("strong", null, "시뮬레이션 기반"),
        document.createTextNode(info.note),
      );
  }

  function errorBox(msg) {
    var b = el("div", "status-msg error");
    b.setAttribute("role", "alert");
    b.appendChild(document.createTextNode(msg));
    b.appendChild(document.createElement("br"));
    add(
      b,
      document.createTextNode(
        "파일을 직접 열면(file://) 데이터를 읽을 수 없습니다. 프로젝트 폴더에서 ",
      ),
      el("code", null, "python -m src.mock_server"),
      document.createTextNode(
        " 실행 후 http://localhost:8000/dashboard/ 로 접속하세요.",
      ),
    );
    return b;
  }

  // -------------------------------------------------- 공통 부품
  function pageHead(title, sub, extra) {
    var h = el("div", "page-head"),
      t = el("div");
    add(t, el("h1", null, title), el("p", "sub", sub));
    return add(h, t, extra);
  }
  function panel(title, sub, extra) {
    var s = el("section", "panel");
    if (title) {
      var h = el("div", "panel-head"),
        h2 = el("h2", null, title);
      if (sub) h2.appendChild(el("span", "h2-sub", " · " + sub));
      add(h, h2, extra);
      s.appendChild(h);
    }
    return s;
  }
  function stat(label, value, unit, note, opts) {
    opts = opts || {};
    var c = el("div", "stat"),
      l = el("span", "stat-label", label),
      v = el("span", "stat-value" + (opts.tone ? " " + opts.tone : ""), value);
    if (opts.tag) l.appendChild(el("span", "tag-outline", opts.tag));
    if (unit && value !== "—") v.appendChild(el("span", "unit", unit));
    add(c, l, v);
    if (note instanceof Node) c.appendChild(note);
    else if (note) c.appendChild(el("span", "stat-note", note));
    return c;
  }
  function stateBadge(key) {
    var s = M.TRAP_STATE[key];
    var b = el("span", "badge st-" + key);
    add(b, el("span", "icon", s.icon), document.createTextNode(s.label));
    b.firstChild.setAttribute("aria-hidden", "true");
    return b;
  }
  function table(head, rows, cls) {
    var t = el("table", cls || "tbl"),
      tr = el("tr");
    head.forEach(function (h) {
      var th = el("th", h.num ? "num" : null, h.text || h);
      tr.appendChild(th);
    });
    t.appendChild(add(el("thead"), tr));
    var body = el("tbody");
    rows.forEach(function (r) {
      var row = el("tr");
      r.forEach(function (c, i) {
        var td = el("td", head[i] && head[i].num ? "num" : null);
        if (c instanceof Node) td.appendChild(c);
        else td.textContent = c;
        row.appendChild(td);
      });
      body.appendChild(row);
    });
    t.appendChild(body);
    var wrap = el("div", "table-scroll");
    wrap.appendChild(t);
    return wrap;
  }
  /** 막대 차트(div 기반). bars: [{label, value, title, hl}], max: 눈금 최대 */
  function barChart(bars, max, ticks, opts) {
    opts = opts || {};
    var box = el("div", "bchart"),
      yax = el("div", "y-axis");
    var n = ticks || 4;
    for (var i = n; i >= 0; i--)
      yax.appendChild(el("span", null, String(Math.round((max / n) * i))));
    var plot = el("div", "plot-col"),
      area = el("div", "plot-area");
    area.style.gap = (opts.gap || 4) + "px";
    bars.forEach(function (b) {
      var col = el("div", "bar" + (b.hl ? " hl" : ""));
      col.style.height =
        (b.value ? Math.max(2, (b.value / max) * 100) : 0) + "%";
      col.title = b.title || "";
      area.appendChild(col);
    });
    var labels = el("div", "x-axis");
    (opts.xlabels || []).forEach(function (t) {
      labels.appendChild(el("span", null, t));
    });
    return add(box, yax, add(plot, area, labels));
  }
  function download(name, text) {
    var blob = new Blob(["﻿" + text], { type: "text/csv;charset=utf-8" });
    var a = el("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () {
      URL.revokeObjectURL(a.href);
    }, 1000);
  }

  var lastCtx = null;

  /** 각 페이지가 호출. page(ctx, main, rerender)는 main을 비우고 다시 그리는 함수. */
  function mount(active, page) {
    document.body.textContent = "";
    var shell = el("div", "shell"),
      col = el("div", "main-col");
    var banner = el("div", "sim-banner");
    banner.setAttribute("role", "note");
    banner.hidden = true;
    var main = el("main", "content");
    main.id = "page";
    add(col, buildTopbar(active), banner, main);
    add(shell, buildNav(active), col);
    document.body.appendChild(shell);

    function draw() {
      if (!lastCtx) return;
      renderBanner(banner, lastCtx.recs);
      if (active === "external") banner.hidden = true; // 트랩 데이터를 쓰지 않는 화면
      main.textContent = "";
      page(lastCtx, main, draw);
    }
    function refresh() {
      return D.load()
        .then(function (ctx) {
          ctx.settings = D.loadSettings();
          lastCtx = ctx;
          setConn(
            true,
            (cfg.apiBase
              ? "실시간 연결됨 · " + cfg.refreshMs / 1000 + "초 간격 갱신 · "
              : "샘플 데이터 · 자동 갱신 없음 · ") +
              "기준 시각 " +
              M.fmtDateTime(ctx.serverTime),
          );
          draw();
        })
        .catch(function (e) {
          setConn(
            false,
            cfg.apiBase
              ? "연결 끊김 — 다시 시도 중"
              : "데이터를 불러오지 못했습니다",
          );
          if (!lastCtx) {
            main.textContent = "";
            main.appendChild(
              errorBox("데이터를 불러오지 못했습니다: " + e.message),
            );
          }
        });
    }
    refresh();
    if (cfg.apiBase) setInterval(refresh, cfg.refreshMs);
  }

  root.Dash = {
    mount: mount,
    el: el,
    add: add,
    svg: svg,
    pageHead: pageHead,
    panel: panel,
    stat: stat,
    stateBadge: stateBadge,
    table: table,
    barChart: barChart,
    download: download,
  };
})(window);
