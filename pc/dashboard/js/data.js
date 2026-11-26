/* 데이터 로딩과 브라우저 설정 저장. apiBase가 있으면 Pi API, 없으면 data/mock 정적 파일(응답 형식 동일). */
(function (root) {
  "use strict";
  var cfg = root.DASHBOARD_CONFIG, M = root.DashModel;
  var SETTINGS_KEY = "smarttrap.settings.v1";

  function getJson(url) {
    return fetch(url, { headers: { Accept: "application/json" } }).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status + " (" + url + ")");
      return res.json();
    });
  }

  /** 목록 API: 페이지를 끝까지 읽는다. 정적 파일은 한 번에 전부 들어 있다. */
  function getList(api, file, range) {
    if (!cfg.apiBase) return getJson(cfg.mockDir + "/" + file).then(function (d) { return d.data || []; });
    var base = cfg.apiBase.replace(/\/$/, "") + "/" + api;
    var q = range ? "from=" + encodeURIComponent(range.from) + "&to=" + encodeURIComponent(range.to) + "&" : "";
    var all = [];
    function page(n) {
      return getJson(base + "?" + q + "page=" + n + "&page_size=1000").then(function (d) {
        all = all.concat(d.data || []);
        var total = d.meta && d.meta.total;
        return typeof total === "number" && all.length < total && (d.data || []).length > 0 && n < 100 ? page(n + 1) : all;
      });
    }
    return page(1);
  }

  function iso(t) {
    return new Date(t + 9 * 3600 * 1000).toISOString().slice(0, 19) + "+09:00";
  }

  function load() {
    var api = cfg.apiBase && cfg.apiBase.replace(/\/$/, "");
    var health = api ? getJson(api + "/health") : getJson(cfg.mockDir + "/health.json");
    return health.then(function (h) {
      var now = M.ms(h.server_time);
      if (now === null) throw new Error("서버 시각(server_time)을 읽을 수 없습니다");
      var range = { from: iso(now - cfg.historyDays * 86400000), to: iso(now + 60000) };
      var recs = (api ? getJson(api + "/recommendations") : getJson(cfg.mockDir + "/recommendations_sample.json"))
        .catch(function () { return null; }); // 추천 결과가 아직 없어도 나머지 화면은 보여준다
      return Promise.all([
        getList("traps", "traps.json"), getList("locations", "locations.json"),
        getList("trap-location-history", "trap_location_history.json"),
        getList("sensor-readings", "sensor_readings.json", range),
        getList("detection-events", "detection_events.json", range), recs,
      ]).then(function (r) {
        return { now: now, serverTime: h.server_time, traps: r[0], locations: r[1], history: r[2],
          readings: r[3], events: r[4], recs: r[5], source: api ? "api" : "mock" };
      });
    });
  }

  // 목표종·임계값 설정: 서버에 저장하는 API가 아직 없어 이 브라우저(localStorage)에만 저장한다.
  var DEFAULTS = { species: {}, defaultSpecies: ["쥐"], doorConfidence: 0.85, eco2Threshold: 1000 };

  function loadSettings() {
    var s = {};
    try { s = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") || {}; } catch (e) { s = {}; }
    return {
      species: s.species && typeof s.species === "object" ? s.species : DEFAULTS.species,
      defaultSpecies: DEFAULTS.defaultSpecies,
      doorConfidence: typeof s.doorConfidence === "number" ? s.doorConfidence : DEFAULTS.doorConfidence,
      eco2Threshold: typeof s.eco2Threshold === "number" ? s.eco2Threshold : DEFAULTS.eco2Threshold,
    };
  }
  function saveSettings(s) {
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(s)); return true; } catch (e) { return false; }
  }
  function speciesOf(settings, trapId) {
    return settings.species[trapId] || settings.defaultSpecies;
  }

  root.DashData = { load: load, loadSettings: loadSettings, saveSettings: saveSettings, speciesOf: speciesOf };
})(window);
