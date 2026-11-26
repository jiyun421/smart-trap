/* 04 설치 위치 추천 (지도 + 선택한 트랩의 분석 결과) */
(function () {
  "use strict";
  var M = DashModel,
    U = Dash,
    el = U.el,
    add = U.add;
  var SVG_NS = "http://www.w3.org/2000/svg";
  var selId = null;

  function statGroup(title, pairs) {
    var g = el("div", "stat-group"),
      dl = el("dl");
    add(g, el("h4", null, title));
    pairs.forEach(function (p) {
      add(dl, add(el("div"), el("dt", null, p[0]), el("dd", null, p[1])));
    });
    return add(g, dl);
  }

  Dash.mount("recommend", function (ctx, main, redraw) {
    var recs = (ctx.recs && ctx.recs.recommendations) || [];
    var review = M.sortRecommendations(recs).filter(function (r) {
      return r.status === "recommended";
    });
    if (
      selId &&
      !review.some(function (r) {
        return r.trap_id === selId;
      })
    )
      selId = null;
    var sel =
      review.filter(function (r) {
        return r.trap_id === selId;
      })[0] || null;

    var locs = {};
    ctx.locations.forEach(function (l) {
      locs[l.location_id] = l;
    });
    var xs = ctx.locations.map(function (l) {
        return l.x;
      }),
      ys = ctx.locations.map(function (l) {
        return l.y;
      });
    var maxX = Math.max.apply(null, xs.concat([1])) + 1,
      maxY = Math.max.apply(null, ys.concat([1])) + 1;
    function pos(locId) {
      var l = locs[locId];
      return l && typeof l.x === "number" && typeof l.y === "number"
        ? { x: 10 + (l.x / maxX) * 80, y: 10 + (l.y / maxY) * 70 }
        : null;
    }

    // 머리말 + 재배치 검토 선택 버튼
    var pills = el("div", "pills");
    pills.appendChild(document.createTextNode("재배치 검토 "));
    if (!review.length) pills.appendChild(el("span", "muted", "없음"));
    review.forEach(function (r) {
      var on = r.trap_id === selId,
        b = el("button", "pill" + (on ? " on" : ""));
      b.type = "button";
      b.setAttribute("aria-pressed", on ? "true" : "false");
      add(
        b,
        el("b", null, r.trap_id),
        document.createTextNode(" · 위치 점수 " + M.fmtNum(r.score, 2)),
      );
      b.onclick = function () {
        selId = r.trap_id;
        redraw();
      };
      pills.appendChild(b);
    });
    main.appendChild(
      U.pageHead(
        "설치 위치 추천",
        "지도에서 재배치 검토 트랩을 선택하면 분석 결과와 추천 위치가 표시됩니다",
        pills,
      ),
    );
    if (!ctx.recs)
      main.appendChild(
        el(
          "div",
          "status-msg",
          "아직 저장된 추천 결과가 없습니다. 추천 실행 후 표시됩니다.",
        ),
      );

    var wrap = el("div", "rec-wrap"),
      mapPanel = U.panel("설치 지도", "감지 밀도(쥐 감지 위치별 누적)");
    var map = el("div", "map");

    // 감지 밀도: 감지 시점에 트랩이 있던 위치별 건수
    var rat = ctx.events.filter(function (e) {
      return e.classification === "rat";
    });
    var dens = M.locationCounts(rat, ctx.history),
      dMax = Math.max.apply(
        null,
        Object.keys(dens)
          .map(function (k) {
            return dens[k];
          })
          .concat([1]),
      );
    Object.keys(dens).forEach(function (id) {
      var p = pos(id);
      if (!p) return;
      var h = el("div", "heat");
      h.setAttribute("aria-hidden", "true");
      h.style.left = p.x + "%";
      h.style.top = p.y + "%";
      var size = 80 + (140 * dens[id]) / dMax;
      h.style.width = h.style.height = size + "px";
      map.appendChild(h);
    });

    // 위치 표시 (후보 위치는 점선)
    ctx.locations.forEach(function (l) {
      var p = pos(l.location_id);
      if (!p) return;
      var m = el("div", "loc" + (l.is_candidate ? " cand" : ""));
      m.style.left = p.x + "%";
      m.style.top = p.y + "%";
      m.appendChild(
        el("span", null, l.name + (l.is_candidate ? " (후보)" : "")),
      );
      map.appendChild(m);
    });

    // 선택한 트랩: 현재 → 추천 위치 화살표
    if (sel) {
      var a = pos(sel.current_location_id),
        b = pos(sel.recommended_location_id);
      if (a && b) {
        var s = document.createElementNS(SVG_NS, "svg");
        s.setAttribute("class", "map-arrow");
        s.setAttribute("aria-hidden", "true");
        s.setAttribute("viewBox", "0 0 100 100");
        s.setAttribute("preserveAspectRatio", "none");
        var ln = document.createElementNS(SVG_NS, "line");
        ln.setAttribute("x1", a.x);
        ln.setAttribute("y1", a.y);
        ln.setAttribute("x2", b.x);
        ln.setAttribute("y2", b.y);
        ln.setAttribute("stroke", "currentColor");
        ln.setAttribute("stroke-width", "3");
        ln.setAttribute("stroke-dasharray", "8 6");
        ln.setAttribute("vector-effect", "non-scaling-stroke");
        s.appendChild(ln);
        map.appendChild(s);
        var tag = el(
          "div",
          "rec-tag",
          "추천 위치 · " +
            (locs[sel.recommended_location_id]
              ? locs[sel.recommended_location_id].name
              : sel.recommended_location_id),
        );
        tag.style.left = b.x + "%";
        tag.style.top = b.y + "%";
        map.appendChild(tag);
      }
    }

    // 트랩 핀 (같은 위치의 트랩은 옆으로 나란히)
    var pins = ctx.traps.map(function (t) {
      return { id: t.trap_id, loc: t.location_id };
    });
    recs.forEach(function (r) {
      if (
        !pins.some(function (p) {
          return p.id === r.trap_id;
        })
      )
        pins.push({ id: r.trap_id, loc: r.current_location_id });
    });
    var perLoc = {};
    pins.forEach(function (p) {
      var pt = pos(p.loc);
      if (!pt) return;
      var n = (perLoc[p.loc] = (perLoc[p.loc] || 0) + 1);
      var total = pins.filter(function (q) {
        return q.loc === p.loc;
      }).length;
      var isRev = review.some(function (r) {
        return r.trap_id === p.id;
      });
      var node = el(
        isRev ? "button" : "div",
        "pin" + (isRev ? " rev" : "") + (p.id === selId ? " on" : ""),
      );
      if (isRev) {
        node.type = "button";
        node.setAttribute("aria-pressed", p.id === selId ? "true" : "false");
        node.setAttribute("aria-label", p.id + " 재배치 분석 보기");
        node.onclick = function () {
          selId = p.id;
          redraw();
        };
      }
      node.style.left =
        "calc(" + pt.x + "% + " + (n - 1 - (total - 1) / 2) * 56 + "px)";
      node.style.top = "calc(" + pt.y + "% + 34px)";
      add(
        node,
        el("span", "pin-dot"),
        el("span", "pin-label", p.id + (isRev ? " · 검토" : "")),
      );
      map.appendChild(node);
    });

    if (!sel && review.length)
      map.appendChild(
        el(
          "div",
          "map-hint",
          "파란 테두리 트랩을 누르면 분석 결과와 추천 위치가 표시됩니다",
        ),
      );
    var lgd = el("div", "map-legend");
    [
      ["lg navy", "운영 중 트랩"],
      ["lg ring", "재배치 검토 (선택 가능)"],
      ["lg cand", "후보 위치"],
      ["lg heat", "감지 밀도 높음"],
    ].forEach(function (x) {
      lgd.appendChild(
        add(el("span"), el("i", x[0]), document.createTextNode(x[1])),
      );
    });
    mapPanel.appendChild(map);
    mapPanel.appendChild(lgd);
    wrap.appendChild(mapPanel);

    if (sel) {
      var cur = locs[sel.current_location_id],
        rec = locs[sel.recommended_location_id];
      var close = el("button", "icon-btn", "×");
      close.type = "button";
      close.setAttribute("aria-label", "분석 결과 닫기");
      close.onclick = function () {
        selId = null;
        redraw();
      };
      var side = el("section", "panel side");
      side.setAttribute("aria-labelledby", "h-panel");
      var head = el("div", "side-head"),
        t = el("div"),
        sc = el("div", "score");
      var h2 = el("h2", null, sel.trap_id + " 재배치 추천");
      h2.id = "h-panel";
      add(t, el("span", "muted", "분석 결과"), h2);
      add(
        sc,
        el("div", "muted", "추천 위치 점수"),
        el("div", "score-num", M.fmtNum(sel.score, 2)),
        el("div", "muted", "상대값 · 최고 1.00"),
      );
      add(head, t, add(el("div", "score-wrap"), sc, close));
      side.appendChild(head);

      var route = el("div", "route-box");
      add(
        route,
        add(
          el("div", "loc-box"),
          el("div", "muted", "현재 위치"),
          el("b", null, cur ? cur.name : sel.current_location_id),
        ),
        el("span", "arrow", "→"),
        add(
          el("div", "loc-box rec"),
          el("div", "muted", "추천 위치"),
          el("b", null, rec ? rec.name : sel.recommended_location_id || "—"),
        ),
      );
      side.appendChild(route);

      var rs = el("div", "reasons-box");
      rs.appendChild(el("h3", null, "추천 근거"));
      (sel.reasons || []).forEach(function (txt, i) {
        add(
          rs,
          add(
            el("div", "reason"),
            el("span", "num-dot", String(i + 1)),
            el("span", null, txt),
          ),
        );
      });
      side.appendChild(rs);

      side.appendChild(
        U.table(
          [
            "지표",
            { text: "현재 위치", num: true },
            { text: "추천 위치", num: true },
          ],
          [
            [
              "위치 점수 (상대값)",
              M.fmtNum(sel.current_location_score, 2),
              M.fmtNum(sel.score, 2),
            ],
          ],
        ),
      );
      var a2 = sel.actual_stats || {},
        s2 = sel.simulated_stats || {};
      side.appendChild(
        statGroup(
          M.detectionLabel(ctx.recs && ctx.recs.data_basis) + " · 현재 위치",
          [
            [
              "작동 시간",
              a2.operating_hours == null
                ? "—"
                : M.fmtNum(a2.operating_hours, 1) + "h",
            ],
            [
              "쥐 감지",
              a2.rat_detections == null
                ? "—"
                : M.fmtCount(a2.rat_detections) + "건",
            ],
            ["시간당 감지", M.fmtNum(a2.rat_detections_per_hour, 3)],
          ],
        ),
      );
      side.appendChild(
        statGroup("가상 포획 (시뮬레이션 추정) · 현재 위치", [
          [
            "가상 포획",
            s2.captures == null ? "—" : M.fmtCount(s2.captures) + "건",
          ],
          ["전환율", M.fmtPct(s2.capture_conversion_rate)],
          ["시간당 포획", M.fmtNum(s2.captures_per_hour, 3)],
        ]),
      );
      side.appendChild(
        el(
          "p",
          "muted",
          "추천 위치의 감지·포획 통계는 추천 결과에 아직 포함되어 있지 않아 비교하지 않습니다.",
        ),
      );
      var more = el("a", "btn", "상세 데이터");
      more.href = "analysis.html";
      side.appendChild(more);
      wrap.appendChild(side);
    }
    main.appendChild(wrap);

    var V = M.VALIDATION,
      vp = U.panel(
        "추천 방식 검증 근거",
        null,
        el("span", "tag-outline", V.badge),
      );
    add(vp, el("p", null, V.summary));
    var vl = el("ul", "val-list");
    V.caveats.forEach(function (c) {
      vl.appendChild(el("li", null, c));
    });
    add(vp, el("h4", null, "한계"), vl);
    main.appendChild(vp);
  });
})();
