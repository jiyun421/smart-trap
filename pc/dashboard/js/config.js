/* 데이터 출처 설정.
 * apiBase가 null이면 data/mock 의 샘플 파일을 읽는다(개발용).
 * Pi 백엔드를 쓰려면 서버 주소를 지정한다. 백엔드가 대시보드를 같이 서빙하면 "/", 다른 서버면 "http://<Pi>:5000".
 * (경로의 /api 와 /health 는 코드가 붙인다.) 지정하면 10초마다 다시 읽어 화면을 갱신한다.
 * 조회 API는 기본적으로 토큰이 필요하므로 백엔드를 TRAP_READ_AUTH=off 로 실행해야 한다. */
window.DASHBOARD_CONFIG = {
  apiBase: null,
  mockDir: "../data/mock",
  historyDays: 14,
  refreshMs: 10000,
};
