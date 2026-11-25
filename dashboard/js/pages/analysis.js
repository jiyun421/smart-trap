/* 03 감지·포획 분석 */
(function () {
  "use strict";
  var M = DashModel,
    U = Dash,
    el = U.el,
    add = U.add;
  var SVG_NS = "http://www.w3.org/2000/svg";
  var period = "7d",
    trapSel = "all",
    envKey = "temperature_c";

  function select(label, opts, value, onChange) {
    var l = el("label", "field", label),
      s = el("select");
    opts.forEach(function (o) {
      var op = el("option", null, o[1]);
      op.value = o[0];
      if (o[0] === value) op.selected = true;
      s.appendChild(op);
    });
    s.onchange = function () {
      onChange(s.value);
    };
    return add(l, s);
  }

  Dash.mount("analysis", function (ctx, main, redraw) {
    var now = ctx.now,
      DAY = 86400000,
      basis = ctx.recs && ctx.recs.data_basis;
    var days = { "24h": 1, "7d": 7, all: 14 }[period];
    var from = now - days * DAY;
    var fEvents = M.inWindow(ctx.events, "detected_at", from, now).filter(
      function (e) {
        return trapSel === "all" || e.trap_id === trapSel;
      },
    );
    var rat = fEvents.filter(function (e) {
      return e.classification === "rat";
    });
    var non = fEvents.filter(function (e) {
      return e.classification === "non_rat";
    });
    var unk = fEvents.length - rat.length - non.length;

    var chip = el(
      "span",
      "sim-chip",
      "가상 포획 결과 포함 — 실제 포획 수가 아닌 시뮬레이션 기반 추정치",
    );
    main.appendChild(
      U.pageHead(
        "감지·포획 분석",
        "트랩 내부 진입·포획 이력과 환경 데이터",
        M.basisInfo(basis).simulated ? chip : null,
      ),
    );

    // 조회 조건
    var form = el("form", "filters");
    form.setAttribute("aria-label", "조회 조건");
    form.onsubmit = function (e) {
      e.preventDefault();
    };
    var traps = [["all", "전체 트랩"]].concat(
      ctx.traps.map(function (t) {
        return [t.trap_id, t.trap_id];
      }),
    );
    var csv = el("button", "btn", "CSV 내보내기");
    csv.type = "button";
    add(
      form,
      select(
        "조회 기간",
        [
          ["7d", "최근 7일"],
          ["24h", "최근 24시간"],
          ["all", "전체 (14일)"],
        ],
        period,
        function (v) {
          period = v;
          redraw();
        },
      ),
      select("트랩 선택", traps, trapSel, function (v) {
        trapSel = v;
        redraw();
      }),
      el(
        "span",
        "muted",
        "기간 " + M.kstDate(from) + " ~ " + M.kstDate(now - 1),
      ),
      csv,
    );
    main.appendChild(form);

    // 가상 포획은 추천 분석 기간 기준의 트랩별 요약만 있다(조회 기간·시간대로 나눌 수 없음)
    var recs = ((ctx.recs && ctx.recs.recommendations) || []).filter(
      function (r) {
        return trapSel === "all" || r.trap_id === trapSel;
      },
    );
    var capKnown = recs.filter(function (r) {
      return (
        r.simulated_stats && typeof r.simulated_stats.captures === "number"
      );
    });
    var caps = capKnown.reduce(function (a, r) {
      return a + r.simulated_stats.captures;
    }, 0);
    var ratsIn = capKnown.reduce(function (a, r) {
      return a + ((r.actual_stats || {}).rat_detections || 0);
    }, 0);
    var conv = capKnown.length && ratsIn > 0 ? caps / ratsIn : null;
    var recPeriod = ctx.recs
      ? "추천 분석 기간 " + M.periodLabel(ctx.recs.analysis_period)
      : "";

    var kp = el("section", "grid-stats");
    kp.setAttribute("aria-label", "요약 지표");
    add(
      kp,
      U.stat(
        "목표종 감지 횟수",
        M.fmtInt(rat.length),
        "회",
        "적외선 진입 + AI 목표종 식별 · " + M.detectionLabel(basis),
      ),
      U.stat(
        "포획 횟수",
        capKnown.length ? M.fmtInt(caps) : "—",
        "회",
        recPeriod || "추천 결과 없음",
        { tag: "가상 포획 결과" },
      ),
      U.stat(
        "포획 전환율",
        conv === null ? "—" : (conv * 100).toFixed(0),
        "%",
        "가상 포획 ÷ 쥐 감지 (같은 추천 분석 기간)",
      ),
      U.stat(
        "비목표종 진입",
        M.fmtInt(non.length),
        "회",
        "도어 미작동 · 미식별 " + unk + "회 제외",
      ),
    );
    main.appendChild(kp);

    // 시간대별 감지
    var p1 = U.panel(
      "시간대별 감지 추이",
      (period === "24h" ? "최근 24시간" : "최근 " + days + "일 누적") +
        (trapSel === "all" ? ", 전체 트랩" : ", " + trapSel),
    );
    var h = M.hourOfDay(rat),
      mx = Math.ceil(Math.max.apply(null, h.concat([4])) / 4) * 4;
    p1.appendChild(
      U.barChart(
        h.map(function (v, i) {
          return {
            value: v,
            title: String(i).padStart(2, "0") + "시 · 감지 " + v + "회",
          };
        }),
        mx,
        4,
        {
          xlabels: [
            "00시",
            "03시",
            "06시",
            "09시",
            "12시",
            "15시",
            "18시",
            "21시",
            "23시",
          ],
          gap: 3,
        },
      ),
    );
    var tot = h.reduce(function (a, b) {
        return a + b;
      }, 0),
      best = 0,
      bestV = -1;
    for (var i = 0; i + 3 < 24; i++) {
      var s4 = h[i] + h[i + 1] + h[i + 2] + h[i + 3];
      if (s4 > bestV) {
        bestV = s4;
        best = i;
      }
    }
    p1.appendChild(
      el(
        "p",
        "muted",
        tot
          ? "감지 집중 시간대: " +
              best +
              "–" +
              (best + 4) +
              "시 (전체 감지의 " +
              Math.round((bestV / tot) * 100) +
              "%)"
          : "선택한 조건에 감지가 없습니다.",
      ),
    );
    p1.appendChild(
      el(
        "p",
        "muted",
        "포획의 시간대별 추이는 트랩별 요약만 제공되어 표시하지 않습니다.",
      ),
    );
    main.appendChild(p1);

    // 환경 × 감지
    var row = el("div", "grid-2"),
      tabs = el("div", "seg");
    [
      ["temperature_c", "온도"],
      ["humidity_pct", "습도"],
    ].forEach(function (o) {
      var b = el("button", "seg-btn" + (envKey === o[0] ? " on" : ""), o[1]);
      b.type = "button";
      b.setAttribute("aria-pressed", envKey === o[0] ? "true" : "false");
      b.onclick = function () {
        envKey = o[0];
        redraw();
      };
      tabs.appendChild(b);
    });
    var envName = envKey === "temperature_c" ? "온도" : "습도",
      unit = envKey === "temperature_c" ? "℃" : "%";
    var p2 = U.panel("환경 데이터 × 감지", "일별", tabs);
    var daily = M.dailyCounts(rat, now, Math.max(days, 3));
    var rd = ctx.readings.filter(function (r) {
      return trapSel === "all" || r.trap_id === trapSel;
    });
    var env = M.dailyAvg(
      rd,
      envKey,
      daily.map(function (d) {
        return d.date;
      }),
    );
    var cm = Math.max.apply(
      null,
      daily
        .map(function (d) {
          return d.count;
        })
        .concat([1]),
    );
    var vals = env.filter(function (v) {
      return v !== null;
    });
    var lo = vals.length ? Math.min.apply(null, vals) : 0,
      hi = vals.length ? Math.max.apply(null, vals) : 1;
    if (hi - lo < 1) {
      lo -= 1;
      hi += 1;
    }
    var box = el("div", "envchart"),
      bars = el("div", "env-bars");
    daily.forEach(function (d) {
      var b = el("div", "env-bar");
      b.style.height = (d.count ? Math.max(2, (d.count / cm) * 100) : 0) + "%";
      b.title = d.date + " · 감지 " + d.count + "회";
      bars.appendChild(b);
    });
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 100 100");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("class", "env-line");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "일별 평균 " + envName + " 추이");
    var segs = [],
      pts = [];
    env.forEach(function (v, i) {
      if (v === null) {
        if (pts.length) segs.push(pts);
        pts = [];
        return;
      } // 결측 구간은 선을 끊는다
      pts.push(
        ((100 / daily.length) * (i + 0.5)).toFixed(1) +
          "," +
          (90 - ((v - lo) / (hi - lo)) * 80).toFixed(1),
      );
    });
    if (pts.length) segs.push(pts);
    segs.forEach(function (p) {
      var pl = document.createElementNS(SVG_NS, "polyline");
      pl.setAttribute("points", p.join(" "));
      pl.setAttribute("fill", "none");
      pl.setAttribute("vector-effect", "non-scaling-stroke");
      pl.setAttribute("stroke", "currentColor");
      pl.setAttribute("stroke-width", "2.5");
      svg.appendChild(pl);
    });
    add(box, bars, svg);
    p2.appendChild(box);
    var xl = el("div", "x-axis spread");
    daily.forEach(function (d) {
      xl.appendChild(el("span", null, d.date.slice(5).replace("-", "/")));
    });
    p2.appendChild(xl);
    var r = M.pearson(
      daily.map(function (d) {
        return d.count;
      }),
      env,
    );
    var lg = el("div", "legend");
    add(
      lg,
      add(
        el("span"),
        el("i", "sw teal-l"),
        document.createTextNode("목표종 감지"),
      ),
      add(
        el("span"),
        el("i", "sw line"),
        document.createTextNode(
          "평균 " +
            envName +
            (vals.length
              ? " (" + M.fmtNum(lo, 1) + "–" + M.fmtNum(hi, 1) + unit + ")"
              : ""),
        ),
      ),
      el("span", null, "상관계수 r = " + M.fmtNum(r, 2)),
    );
    p2.appendChild(lg);
    if (r === null)
      p2.appendChild(
        el(
          "p",
          "muted",
          "일수가 3일 미만이거나 값이 일정해 상관계수를 계산할 수 없습니다.",
        ),
      );

    // 트랩별 감지·포획
    var p3 = U.panel(
      "트랩별 감지·포획",
      null,
      el("span", "tag t-blue", "가상 포획 결과"),
    );
    var perTrap = ctx.traps
      .filter(function (t) {
        return trapSel === "all" || t.trap_id === trapSel;
      })
      .map(function (t) {
        var d = rat.filter(function (e) {
          return e.trap_id === t.trap_id;
        }).length;
        var rc = recs.filter(function (x) {
          return x.trap_id === t.trap_id;
        })[0];
        var s = rc && rc.simulated_stats;
        return {
          id: t.trap_id,
          d: d,
          c: s && typeof s.captures === "number" ? s.captures : null,
          cr:
            s && typeof s.capture_conversion_rate === "number"
              ? s.capture_conversion_rate
              : null,
        };
      });
    p3.appendChild(
      U.table(
        [
          "트랩",
          { text: "감지(조회 기간)", num: true },
          { text: "가상 포획(분석 기간)", num: true },
          "전환율",
        ],
        perTrap.map(function (t) {
          var bar = el("div", "rate"),
            track = el("div", "rate-track"),
            fill = el("div", "rate-fill");
          fill.style.width =
            t.cr === null ? "0%" : Math.min(100, t.cr * 100) + "%";
          add(bar, add(track, fill), el("span", "rate-num", M.fmtPct(t.cr)));
          return [t.id, M.fmtCount(t.d), M.fmtCount(t.c), bar];
        }),
      ),
    );
    p3.appendChild(
      el(
        "p",
        "muted",
        "가상 포획·전환율은 추천 분석 기간 기준이라 조회 기간과 다를 수 있습니다. ‘—’는 계산 불가입니다.",
      ),
    );
    add(main, add(row, p2, p3));

    csv.onclick = function () {
      U.download(
        "detections_" + M.kstDate(now - 1) + ".csv",
        M.toCsv(
          [
            "trap_id",
            "detections_in_period",
            "simulated_captures",
            "capture_conversion_rate",
            "data_basis",
          ],
          perTrap.map(function (t) {
            return [t.id, t.d, t.c, t.cr, "simulated"];
          }),
        ),
      );
    };
  });
})();
