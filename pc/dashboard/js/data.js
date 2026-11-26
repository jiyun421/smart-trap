/* 데이터 로딩과 브라우저 설정 저장. apiBase가 있으면 Pi 백엔드(/api/...), 없으면 data/mock 정적 파일. */
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

  var PAGE_LIMIT = 500, MAX_PAGES = 40; // 백엔드 최대 limit, 한 목록당 최대 페이지(최신순으로 읽으므로 오래된 쪽이 잘린다)

  function mockList(file) {
    return getJson(cfg.mockDir + "/" + file).then(function (d) { return d.data || []; });
  }

  function loadMock() {
    return getJson(cfg.mockDir + "/health.json").then(function (h) {
      var now = M.ms(h.server_time);
      if (now === null) throw new Error("서버 시각(server_time)을 읽을 수 없습니다");
      var recs = getJson(cfg.mockDir + "/recommendations_sample.json").catch(function () { return null; });
      return Promise.all([
        mockList("traps.json"), mockList("locations.json"), mockList("trap_location_history.json"),
        mockList("sensor_readings.json"), mockList("detection_events.json"), recs,
      ]).then(function (r) {
        return { now: now, serverTime: h.server_time, traps: r[0], locations: r[1], history: r[2],
          readings: r[3], events: r[4], recs: r[5], source: "mock" };
      });
    });
  }

  /* ---- Pi 백엔드(/api/...). 응답은 DashAdapter가 화면용 형태로 바꾼다. ---- */
  function apiGet(path, params) {
    var q = Object.keys(params || {}).map(function (k) { return k + "=" + encodeURIComponent(params[k]); }).join("&");
    return fetch(cfg.apiBase.replace(/\/$/, "") + (path === "/health" ? "" : "/api") + path + (q ? "?" + q : ""), { headers: { Accept: "application/json" } })
      .then(function (res) {
        if (res.status === 401 || res.status === 403)
          throw new Error("조회 권한이 없습니다. 백엔드를 TRAP_READ_AUTH=off 로 실행하거나 읽기 토큰 설정을 확인하세요.");
        if (!res.ok) throw new Error("HTTP " + res.status + " (" + path + ")");
        return res;
      });
  }

  /** 목록 API: next_offset을 따라 끝까지(최대 MAX_PAGES) 읽는다. */
  function apiItems(path, params) {
    var all = [];
    function page(offset, n) {
      var p = Object.assign({ limit: PAGE_LIMIT, offset: offset }, params);
      return apiGet(path, p).then(function (res) { return res.json(); }).then(function (d) {
        all = all.concat(d.items || []);
        return typeof d.next_offset === "number" && n < MAX_PAGES ? page(d.next_offset, n + 1) : all;
      });
    }
    return page(0, 1);
  }

  function loadApi() {
    return apiGet("/health").then(function (res) {
      var date = res.headers.get("Date"), now = date ? Date.parse(date) : Date.now();
      if (isNaN(now)) now = Date.now();
      var range = { from: new Date(now - cfg.historyDays * 86400000).toISOString(), to: new Date(now + 60000).toISOString() };
      var runs = apiItems("/recommendations").catch(function () { return []; }); // 추천이 아직 없어도 나머지 화면은 보여준다
      return Promise.all([
        apiItems("/traps"), apiItems("/locations"), apiItems("/deployments"),
        apiItems("/readings", range), apiItems("/visits", range), runs,
      ]).then(function (r) {
        return Promise.all(r[0].map(function (t) {
          return apiGet("/traps/" + encodeURIComponent(t.trap_id) + "/status").then(function (x) { return x.json(); });
        })).then(function (statuses) {
          var byTrap = {};
          r[0].forEach(function (t, i) { byTrap[t.trap_id] = statuses[i]; });
          var ctx = root.DashAdapter.build({ traps: r[0], statuses: byTrap, locations: r[1], deployments: r[2],
            readings: r[3], visits: r[4], runs: r[5] });
          ctx.now = now;
          ctx.serverTime = new Date(now).toISOString();
          ctx.source = "api";
          return ctx;
        });
      });
    });
  }

  function load() {
    return cfg.apiBase ? loadApi() : loadMock();
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
