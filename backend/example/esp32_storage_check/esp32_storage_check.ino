#include <WiFi.h>
#include <HTTPClient.h>
#include <esp_system.h>
#include <time.h>

// secrets.example.h를 secrets.h로 복사하고 로컬 장치 설정을 입력하세요.
#include "secrets.h"

const char* HEALTH_URL = PI_BASE_URL "/health";
const char* API_URL = PI_BASE_URL "/api/sensor/data";

bool checkHealth() {
  WiFiClient client;
  HTTPClient http;
  if (!http.begin(client, HEALTH_URL)) {
    Serial.println("Pi 주소를 확인하세요.");
    return false;
  }
  int code = http.GET();
  Serial.printf("GET /health: HTTP %d\n", code);
  Serial.println(code > 0 ? http.getString() : HTTPClient::errorToString(code));
  http.end();
  return code == 200;
}

int postEvent(String& payload) {
  WiFiClient client;
  HTTPClient http;
  if (!http.begin(client, API_URL)) {
    Serial.println("Cannot open API URL");
    return -1;
  }
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Bearer ") + DEVICE_TOKEN);
  int status = http.POST(payload);
  if (status > 0) {
    Serial.printf("HTTP %d\n", status);
    Serial.println(http.getString());
  } else {
    Serial.println(HTTPClient::errorToString(status));
  }
  http.end();
  return status;
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  WiFi.begin(WIFI_NAME, WIFI_PASSWORD);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi 연결 실패");
    return;
  }
  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.localIP());
  if (!checkHealth()) {
    return;
  }
  if (String(DEVICE_TOKEN) == "YOUR_TRAP_01_TOKEN") {
    Serial.println("DEVICE_TOKEN에 trap-01 장치 토큰을 입력하세요.");
    return;
  }

  configTime(0, 0, "pool.ntp.org", "time.google.com");
  struct tm utc;
  if (!getLocalTime(&utc, 20000)) {
    Serial.println("NTP failed: check hotspot internet access");
    return;
  }
  // 저장 검증용 칩 내부 온도. 주변 온도를 측정하려면 외부 센서를 사용하세요.
  float chipC = temperatureRead();
  if (!isfinite(chipC)) {
    Serial.println("Chip temperature unavailable");
    return;
  }
  char observedAt[24], eventId[48], payloadBuffer[320];
  strftime(observedAt, sizeof(observedAt), "%Y-%m-%dT%H:%M:%SZ", &utc);
  snprintf(eventId, sizeof(eventId), "chip-test-%08lx-%08lx",
           (unsigned long)esp_random(), (unsigned long)esp_random());
  snprintf(payloadBuffer, sizeof(payloadBuffer),
           "{\"schema_version\":1,\"trap_id\":\"trap-01\",\"deployment_id\":\"dep-001\","
           "\"event_type\":\"telemetry\",\"event_id\":\"%s\",\"observed_at\":\"%s\","
           "\"env\":{\"temperature_c\":%.2f}}", eventId, observedAt, chipC);
  String payload(payloadBuffer);
  Serial.printf("event_id=%s chip_temperature=%.2f C\n", eventId, chipC);
  if (postEvent(payload) == 201) {
    Serial.println("Resending the identical event");
    postEvent(payload);
  }
}

void loop() {}
