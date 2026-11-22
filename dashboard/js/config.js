/* 데이터 출처 설정.
 * apiBase가 null이면 샘플 파일을 읽는다(개발용). Pi에 올릴 때는 "/api/v1" 처럼 지정한다.
 * 대시보드는 GET {apiBase}/recommendations (최신 run)만 사용한다. */
window.DASHBOARD_CONFIG = {
  apiBase: null,
  sampleUrl: "../data/mock/recommendations_sample.json",
};
