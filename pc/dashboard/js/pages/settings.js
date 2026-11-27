/* 05 설정 — 목표종 / 임계값. 서버 저장 API가 없어 이 브라우저에만 저장한다. */
(function () {
  "use strict";
  var M = DashModel,
    D = DashData,
    U = Dash,
    el = U.el,
    add = U.add;
  var SPECIES = ["쥐", "너구리", "비둘기", "참새"];
  var msg = "";

  Dash.mount("settings", function (ctx, main, redraw) {
    var st = ctx.settings;
    main.appendChild(
      U.pageHead("설정", "목표종과 알림 기준 · 이 브라우저에만 저장됩니다"),
    );
    main.appendChild(
      el(
        "div",
        "status-msg",
        "서버에 설정을 저장하는 API가 아직 없어, 저장한 값은 이 브라우저에서만 적용됩니다. 목표종과 AI 도어 신뢰도 기준은 트랩에 전달되지 않아 실제 도어 동작을 바꾸지 않습니다.",
      ),
    );

    var form = el("form");
    form.setAttribute("aria-label", "설정");
    var p1 = U.panel("트랩별 목표종");
    var checks = {};
    ctx.traps.forEach(function (t) {
      var row = el("fieldset", "set-row"),
        lg = el("legend", null, t.trap_id);
      row.appendChild(lg);
      var cur = D.speciesOf(st, t.trap_id);
      checks[t.trap_id] = SPECIES.map(function (sp) {
        var l = el("label", "check"),
          c = el("input");
        c.type = "checkbox";
        c.checked = cur.indexOf(sp) >= 0;
        add(l, c, document.createTextNode(sp));
        row.appendChild(l);
        return { sp: sp, box: c };
      });
      p1.appendChild(row);
    });
    p1.appendChild(
      el(
        "p",
        "muted",
        "현재 AI 식별은 ‘쥐/비목표종’ 두 분류만 제공하므로, 쥐 외의 목표종은 선택해도 감지 통계에 반영되지 않습니다.",
      ),
    );

    var p2 = U.panel("기준값");
    var conf = el("input");
    conf.type = "range";
    conf.min = "0.5";
    conf.max = "0.99";
    conf.step = "0.01";
    conf.value = String(st.doorConfidence);
    var confOut = el(
      "output",
      "range-out",
      Number(st.doorConfidence).toFixed(2),
    );
    conf.oninput = function () {
      confOut.textContent = Number(conf.value).toFixed(2);
    };
    var lc = el("label", "field wide", "AI 도어 작동 신뢰도 기준 (0.50–0.99)");
    add(lc, conf, confOut);
    var eco = el("input");
    eco.type = "number";
    eco.min = "400";
    eco.max = "5000";
    eco.step = "50";
    eco.value = String(st.eco2Threshold);
    var le = el("label", "field", "eCO₂ 수거 권장 기준 (ppm 이상)");
    le.appendChild(eco);
    add(p2, lc, le);

    var save = el("button", "btn primary", "저장");
    save.type = "submit";
    var cancel = el("button", "btn", "취소");
    cancel.type = "button";
    cancel.onclick = function () {
      msg = "";
      redraw();
    };
    var status = el("span", "muted", msg);
    status.setAttribute("role", "status");
    form.onsubmit = function (e) {
      e.preventDefault();
      var e2 = Number(eco.value);
      if (!isFinite(e2) || e2 < 400 || e2 > 5000) {
        status.textContent = "eCO₂ 기준은 400–5000ppm 사이여야 합니다.";
        return;
      }
      var next = {
        species: {},
        doorConfidence: Number(conf.value),
        eco2Threshold: e2,
      };
      var ok = true;
      Object.keys(checks).forEach(function (id) {
        var picked = checks[id]
          .filter(function (c) {
            return c.box.checked;
          })
          .map(function (c) {
            return c.sp;
          });
        if (!picked.length) ok = false;
        next.species[id] = picked;
      });
      if (!ok) {
        status.textContent = "각 트랩에 목표종을 하나 이상 선택하세요.";
        return;
      }
      msg = D.saveSettings(next)
        ? "저장했습니다 (이 브라우저에만 적용)"
        : "저장하지 못했습니다 (브라우저 저장소 사용 불가)";
      ctx.settings = D.loadSettings();
      redraw();
    };
    add(form, p1, p2, add(el("div", "actions"), save, cancel, status));
    main.appendChild(form);
  });
})();
