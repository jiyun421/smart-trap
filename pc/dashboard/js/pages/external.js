/* 05 외부 데이터 기반 추천: 다른 구역으로 학습한 ML(GBM) 모델의 활동 예측으로 트랩의 이동을 제안한다.
 * 데이터는 data/external_map.json (python -m src.movement_transfer 가 생성). 트랩 ID와 배치는 설치 위치 추천 지도와 같고,
 * 활동 예측은 트랩 데이터·기존 추천과 무관하다. */
(function () {
  "use strict";
  var M = DashModel,
    U = Dash,
    el = U.el,
    add = U.add;
  var NS = "http://www.w3.org/2000/svg";
  var MODEL = "GBM";
  var data = null,
    failed = false,
    loading = false,
    selected = null; // 이유를 보고 있는 이동 추천 트랩 id
  // 보여줄 구역. 결과를 보고 고르지 않도록 첫 구역으로 고정한다.
  var ZONE = "G2";

  /** 모니터링과 같은 트랩을 설치 지도의 배치대로 격자 칸에 놓는다. 좌표가 없는 위치의 트랩은 뺀다. */
  function placedTraps(ctx, n) {
    var pos = M.mapPosition(ctx.locations),
      names = {};
    ctx.locations.forEach(function (l) {
      names[l.location_id] = l.name;
    });
    return ctx.traps
      .filter(function (t) {
        return pos(t.location_id);
      })
      .map(function (t) {
        return {
          id: t.trap_id,
          label: t.trap_id + (t.is_virtual ? " · 가상" : ""),
          place: names[t.location_id],
          cell: M.mapCell(pos(t.location_id), n),
        };
      });
  }

  function pct(v) {
    return (v * 100).toFixed(1) + "%";
  }
  function cellName(id) {
    return (
      "ABCDEFGH".charAt(Math.floor(id / data.cells)) + ((id % data.cells) + 1)
    );
  }
  /** 칸 중심의 지도 내 위치(%). y가 클수록 위쪽. */
  function center(id) {
    var n = data.cells;
    return {
      x: ((Math.floor(id / n) + 0.5) / n) * 100,
      y: ((n - 0.5 - (id % n)) / n) * 100,
    };
  }
  function place(node, id) {
    var p = center(id);
    node.style.left = p.x + "%";
    node.style.top = p.y + "%";
    return node;
  }
  function svgEl(tag, attrs) {
    var e = document.createElementNS(NS, tag);
    Object.keys(attrs).forEach(function (k) {
      e.setAttribute(k, attrs[k]);
    });
    return e;
  }

  /** 이동 화살표. 지도 비율(5:4)과 같은 viewBox를 써서 화살촉이 찌그러지지 않게 한다. */
  function arrows(moves) {
    var s = svgEl("svg", {
      class: "map-arrow ext-arrow",
      viewBox: "0 0 125 100",
      "aria-hidden": "true",
    });
    var head = svgEl("marker", {
      id: "ext-head",
      viewBox: "0 0 10 10",
      refX: 8,
      refY: 5,
      markerWidth: 5,
      markerHeight: 5,
      orient: "auto",
    });
    head.appendChild(
      svgEl("path", { d: "M0 0L10 5L0 10z", fill: "currentColor" }),
    );
    var defs = svgEl("defs", {});
    defs.appendChild(head);
    s.appendChild(defs);
    moves.forEach(function (m) {
      var a = center(m.cell),
        b = center(m.target);
      s.appendChild(
        svgEl("line", {
          x1: a.x * 1.25,
          y1: a.y,
          x2: (a.x + (b.x - a.x) * 0.85) * 1.25,
          y2: a.y + (b.y - a.y) * 0.85,
          stroke: "currentColor",
          "stroke-width": 0.9,
          "marker-end": "url(#ext-head)",
        }),
      );
    });
    return s;
  }

  function mapPanel(fold, traps, moves, movers, redraw) {
    var panel = U.panel("가상 지도 · 구역 " + fold.test_grid);
    var map = el("div", "ext-map");
    map.setAttribute("role", "group");
    map.setAttribute(
      "aria-label",
      "예측 활동 지도와 트랩. 이동 추천 트랩을 누르면 옮길 칸과 이유가 나옵니다.",
    );
    M.externalGrid(fold.shares[MODEL], data.cells).forEach(function (c) {
      var cell = el("div", "ext-cell");
      cell.style.background =
        "color-mix(in srgb, var(--blue) " +
        Math.round(c.level * 75) +
        "%, var(--card))";
      cell.title = cellName(c.id) + " · 예측 활동 " + pct(c.share);
      movers.forEach(function (m, i) {
        if (m.id !== selected || m.target !== c.id) return;
        cell.className += " rec";
        cell.appendChild(el("span", "ext-rank", String(i + 1)));
      });
      map.appendChild(cell);
    });
    map.appendChild(
      arrows(
        movers.filter(function (m) {
          return m.id === selected;
        }),
      ),
    );
    moves.forEach(function (m, i) {
      var trap = traps[i],
        same = traps.filter(function (t) {
          return t.cell === m.cell;
        });
      var rev = m.target !== null,
        on = m.id === selected;
      var pin = place(
        el(
          rev ? "button" : "div",
          "pin" + (rev ? " rev" : "") + (on ? " on" : ""),
        ),
        m.cell,
      );
      if (rev) {
        pin.type = "button";
        pin.setAttribute("aria-pressed", on ? "true" : "false");
        pin.onclick = function () {
          selected = on ? null : m.id;
          redraw();
        };
      }
      // 같은 칸의 트랩은 옆으로 나란히
      pin.style.left =
        "calc(" +
        center(m.cell).x +
        "% + " +
        (same.indexOf(trap) - (same.length - 1) / 2) * 110 +
        "px)";
      pin.title = trap.place;
      add(
        pin,
        el("span", "pin-dot"),
        el("span", "pin-label", trap.label),
        el("span", "pin-label", trap.place),
      );
      map.appendChild(pin);
    });
    panel.appendChild(map);

    var lgd = el("div", "map-legend");
    [
      ["lg ext-high", "진할수록 예측 활동 많음"],
      ["lg navy", "트랩 (유지)"],
      ["lg ring", "트랩 (이동 추천)"],
      ["lg ext-rec", "옮길 칸"],
    ].forEach(function (x) {
      lgd.appendChild(
        add(el("span"), el("i", x[0]), document.createTextNode(x[1])),
      );
    });
    panel.appendChild(lgd);
    return panel;
  }

  function reasons(fold, m) {
    var now = fold.shares[MODEL][m.cell],
      next = fold.shares[MODEL][m.target],
      seen = fold.shares["방문 빈도"];
    var times =
      now > 0 && next / now < 10
        ? "약 " + (next / now).toFixed(1) + "배"
        : "10배 이상";
    return [
      "예측 활동이 " +
        cellName(m.cell) +
        " " +
        pct(now) +
        " → " +
        cellName(m.target) +
        " " +
        pct(next) +
        "로 " +
        times +
        " 많습니다.",
      "관측 " +
        fold.obs_days +
        "일간 실제 위치 기록 비중은 " +
        pct(seen[m.cell]) +
        " → " +
        pct(seen[m.target]) +
        "입니다.",
    ];
  }

  /** 선택한 트랩의 추천 결과와 이유. n은 지도에 표시한 옮길 칸 번호. */
  function resultPanel(fold, trap, m, n, redraw) {
    var side = U.panel("추천 결과");
    side.className += " side";
    side.appendChild(
      add(
        el("h3", "ext-title"),
        el("span", "num-dot", String(n)),
        document.createTextNode(
          trap.label +
            " (" +
            trap.place +
            ") : " +
            cellName(m.cell) +
            " → " +
            cellName(m.target),
        ),
      ),
    );
    var ul = el("ul", "val-list");
    reasons(fold, m).forEach(function (t) {
      ul.appendChild(el("li", null, t));
    });
    side.appendChild(ul);
    var close = el("button", "seg-btn", "닫기");
    close.type = "button";
    close.onclick = function () {
      selected = null;
      redraw();
    };
    side.appendChild(close);
    return side;
  }

  function render(ctx, main, redraw) {
    // 가장 많이 관측한 결과를 보여준다
    var days = Math.max.apply(
      null,
      data.folds.map(function (f) {
        return f.obs_days;
      }),
    );
    var fold = data.folds.filter(function (f) {
      return f.obs_days === days && f.test_grid === ZONE;
    })[0];

    var traps = placedTraps(ctx, data.cells);
    var moves = M.externalMoves(
      fold.shares[MODEL],
      fold.recommended[MODEL],
      traps,
    );
    // 현재 위치 점수가 낮은 트랩부터
    var movers = moves
      .filter(function (m) {
        return m.target !== null;
      })
      .sort(function (a, b) {
        return a.score - b.score;
      });
    var wrap = add(
      el("div", "rec-wrap"),
      mapPanel(fold, traps, moves, movers, redraw),
    );
    var picked = movers.filter(function (m) {
      return m.id === selected;
    })[0];
    if (picked)
      wrap.appendChild(
        resultPanel(
          fold,
          traps[moves.indexOf(picked)],
          picked,
          movers.indexOf(picked) + 1,
          redraw,
        ),
      );
    main.appendChild(wrap);
    main.appendChild(
      el(
        "p",
        null,
        movers.length
          ? movers.length +
              "대 이동 추천 · 테두리가 있는 트랩을 누르면 옮길 칸과 이유가 나옵니다."
          : "이동 추천 트랩이 없습니다.",
      ),
    );
    main.appendChild(
      el(
        "p",
        "muted",
        "야생 설치류 외부 데이터(쥐 아님)로 다른 구역에서 학습한 ML(GBM)의 활동 예측이며, 지도는 가상이며, 트랩 배치는 설치 위치 추천 지도를 옮긴 것일 뿐 실제 설치 환경의 활동 예측이 아닙니다. " +
          "처음 보는 구역 테스트에서 무작위보다 잘 맞았지만 단순 방문 빈도 방식을 넘지는 못했고, 포획 증가 효과는 검증하지 않았습니다.",
      ),
    );
  }

  Dash.mount("external", function (ctx, main, redraw) {
    main.appendChild(
      U.pageHead(
        "외부 데이터 기반 추천",
        "야생동물 데이터로 학습한 모델이 제안하는 트랩 이동 (시연)",
      ),
    );
    if (data) return render(ctx, main, redraw);
    main.appendChild(
      el(
        "div",
        "status-msg",
        failed
          ? "지도 데이터를 불러오지 못했습니다. python -m src.movement_transfer 로 생성하세요."
          : "지도 데이터를 불러오는 중…",
      ),
    );
    if (loading || failed) return;
    loading = true;
    fetch("data/external_map.json")
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      })
      .then(function (j) {
        data = j;
        redraw();
      })
      .catch(function () {
        failed = true;
        redraw();
      });
  });
})();
