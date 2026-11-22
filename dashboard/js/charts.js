/* Chart.js 렌더링. 색은 CSS 변수에서 읽어 라이트/다크 모드를 따른다. */
(function (root) {
  "use strict";
  var instances = [];

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  /** 데이터 부족 막대용 빗금 패턴 (색만으로 구분하지 않기 위함) */
  function hatch(fg, bg) {
    var c = document.createElement("canvas");
    c.width = c.height = 8;
    var g = c.getContext("2d");
    g.fillStyle = bg; g.fillRect(0, 0, 8, 8);
    g.strokeStyle = fg; g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(-1, 9); g.lineTo(9, -1); g.moveTo(-1, 1); g.lineTo(1, -1); g.moveTo(7, 9); g.lineTo(9, 7); g.stroke();
    return g.createPattern(c, "repeat");
  }

  /** 막대 끝에 값을 직접 표기. 결측은 "계산 불가"를 그린다(0 막대를 그리지 않음). */
  var valueLabels = {
    id: "valueLabels",
    afterDatasetsDraw: function (chart, _args, opts) {
      var ctx = chart.ctx, area = chart.chartArea, y = chart.scales.y;
      ctx.save();
      ctx.font = "12px " + getComputedStyle(document.body).fontFamily;
      ctx.fillStyle = opts.color; ctx.textBaseline = "middle";
      chart.data.datasets.forEach(function (ds, di) {
        chart.getDatasetMeta(di).data.forEach(function (bar, i) {
          var v = ds.data[i];
          if (v === null || v === undefined) {
            ctx.fillText("계산 불가", area.left + 6, y.getPixelForValue(i));
            return;
          }
          var text = opts.format(v) + (opts.insufficient && opts.insufficient[i] ? "  (부족)" : "");
          ctx.fillText(text, bar.x + 6, bar.y);
        });
      });
      ctx.restore();
    },
  };

  function base(canvas, rowCount, legend) {
    canvas.parentElement.style.height = (rowCount * (legend ? 54 : 36) + (legend ? 64 : 40)) + "px";
    return {
      indexAxis: "y", responsive: true, maintainAspectRatio: false, animation: false,
      layout: { padding: { right: 8 } },
      scales: {
        x: { beginAtZero: true, grid: { color: cssVar("--grid") }, border: { display: false },
             ticks: { display: false } },
        y: { grid: { display: false }, ticks: { color: cssVar("--ink") } },
      },
      plugins: { legend: { display: !!legend, labels: { color: cssVar("--ink") } } },
    };
  }

  function maxOf(values) {
    var nums = values.filter(function (v) { return typeof v === "number"; });
    return nums.length ? Math.max.apply(null, nums) : 1;
  }

  /** 트랩별 단일 지표 막대. rows: DashModel.chartRows 결과, tips: 툴팁 줄(행과 같은 순서) */
  function singleBar(canvas, rows, format, tips) {
    var blue = cssVar("--blue"), surface = cssVar("--card");
    var opts = base(canvas, rows.length, false);
    var max = maxOf(rows.map(function (r) { return r.value; }));
    opts.scales.x.max = max > 0 ? max * 1.7 : 1;
    opts.plugins.valueLabels = { color: cssVar("--ink"), format: format, insufficient: rows.map(function (r) { return r.insufficient; }) };
    opts.plugins.tooltip = { callbacks: { label: function (c) { return tips[c.dataIndex]; } } };
    instances.push(new Chart(canvas, {
      type: "bar", plugins: [valueLabels], options: opts,
      data: {
        labels: rows.map(function (r) { return r.label; }),
        datasets: [{
          data: rows.map(function (r) { return r.value; }),
          backgroundColor: rows.map(function (r) { return r.insufficient ? hatch(cssVar("--ink-2"), surface) : blue; }),
          borderColor: rows.map(function (r) { return r.insufficient ? cssVar("--ink-2") : blue; }),
          borderWidth: rows.map(function (r) { return r.insufficient ? 1 : 0; }),
          barThickness: 16, borderRadius: 3,
        }],
      },
    }));
  }

  /** 재배치 권고 트랩: 현재 위치 점수(회색) vs 추천 위치 점수(파랑) */
  function scoreCompare(canvas, labels, current, target) {
    var opts = base(canvas, labels.length, true);
    var fmt = function (v) { return v.toFixed(2); };
    opts.scales.x.max = 1.3;
    opts.plugins.valueLabels = { color: cssVar("--ink"), format: fmt };
    instances.push(new Chart(canvas, {
      type: "bar", plugins: [valueLabels], options: opts,
      data: {
        labels: labels,
        datasets: [
          { label: "현재 위치 점수", data: current, backgroundColor: cssVar("--neutral"), barThickness: 14, borderRadius: 3 },
          { label: "추천 위치 점수", data: target, backgroundColor: cssVar("--blue"), barThickness: 14, borderRadius: 3 },
        ],
      },
    }));
  }

  function destroyAll() {
    instances.forEach(function (c) { c.destroy(); });
    instances = [];
  }

  root.DashCharts = { singleBar: singleBar, scoreCompare: scoreCompare, destroyAll: destroyAll };
})(window);
