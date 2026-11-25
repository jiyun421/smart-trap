/* 데이터 출처 설정.
 * apiBase가 null이면 data/mock 의 샘플 파일을 읽는다(개발용). Pi에 올릴 때는 "/api/v1" 처럼 지정한다.
 * apiBase를 지정하면 10초마다 다시 읽어 화면을 갱신한다. */
window.DASHBOARD_CONFIG = {
  apiBase: null,
  mockDir: "../data/mock",
  historyDays: 14,
  refreshMs: 10000,
};
