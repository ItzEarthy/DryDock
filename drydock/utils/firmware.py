from __future__ import annotations


def _escape_cpp_string(value):
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def generate_esp32_firmware(ssid, password, server_url):
    template = r'''#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <Adafruit_AM2320.h>
#include <Adafruit_NAU7802.h>

// -------- Injected at build time --------
const char* WIFI_SSID = "__WIFI_SSID__";
const char* WIFI_PASSWORD = "__WIFI_PASSWORD__";
const char* FLASK_UPDATE_URL = "__SERVER_URL__";

// -------- Pin Layout --------
#define RST_PIN 1
#define SS_PIN  10
#define SCK_PIN 12
#define MISO_PIN 13
#define MOSI_PIN 11

#define I2C1_SDA 4
#define I2C1_SCL 5
#define I2C2_SDA 8
#define I2C2_SCL 9

// -------- Weight Filtering / Hardening --------
float emaWeight = 0.0;
const float EMA_ALPHA = 0.2;

float finalStableWeight = 0.0;
unsigned long lastWeightChangeTime = 0;
const float SETTLE_THRESHOLD = 3.0;
const unsigned long SETTLE_DELAY_MS = 4000;

float calibrationFactor = 426.75;
int32_t zeroOffset = 0;
int32_t latestRawAdc = 0;

MFRC522* mfrc522;
Adafruit_AM2320* am2320_1;
Adafruit_AM2320* am2320_2;
Adafruit_NAU7802* nau;

unsigned long lastSensorRead = 0;
unsigned long lastPostMs = 0;

bool rfidFound = false;
bool am1Found = false;
bool am2Found = false;
bool nauFound = false;

String lastRfidUid = "";

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long started = millis();

  while (WiFi.status() != WL_CONNECTED && millis() - started < 12000) {
    delay(250);
  }
}

String readRfidUid() {
  if (!rfidFound) {
    return "";
  }

  if (!mfrc522->PICC_IsNewCardPresent() || !mfrc522->PICC_ReadCardSerial()) {
    return "";
  }

  String uid = "";
  for (byte i = 0; i < mfrc522->uid.size; i++) {
    if (mfrc522->uid.uidByte[i] < 0x10) {
      uid += "0";
    }
    uid += String(mfrc522->uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  mfrc522->PICC_HaltA();
  mfrc522->PCD_StopCrypto1();
  return uid;
}

void tareScale() {
  if (!nauFound) {
    return;
  }

  int32_t tareSum = 0;
  for (int i = 0; i < 10; i++) {
    while (!nau->available()) {
      delay(1);
    }
    tareSum += nau->read();
  }
  zeroOffset = tareSum / 10;
  emaWeight = 0.0;
  finalStableWeight = 0.0;
  lastWeightChangeTime = millis();
}

void readWeightFilter() {
  if (!nauFound) {
    return;
  }
  if (millis() - lastSensorRead < 100) {
    return;
  }

  lastSensorRead = millis();
  if (!nau->available()) {
    return;
  }

  int32_t currentReading = nau->read();
  latestRawAdc = currentReading;
  float rawWeight = (currentReading - zeroOffset) / calibrationFactor;

  if (fabs(rawWeight - emaWeight) > 50.0) {
    emaWeight = rawWeight;
  } else {
    emaWeight = (EMA_ALPHA * rawWeight) + ((1.0 - EMA_ALPHA) * emaWeight);
  }

  if (fabs(emaWeight - finalStableWeight) > SETTLE_THRESHOLD) {
    finalStableWeight = emaWeight;
    lastWeightChangeTime = millis();
  }
}

int hardeningProgress() {
  unsigned long elapsed = millis() - lastWeightChangeTime;
  if (elapsed >= SETTLE_DELAY_MS) {
    return 100;
  }
  return (int)((elapsed * 100UL) / SETTLE_DELAY_MS);
}

void postTelemetry(float temp1, float hum1, float temp2, float hum2) {
  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  HTTPClient http;
  http.begin(FLASK_UPDATE_URL);
  http.addHeader("Content-Type", "application/json");

  String payload = "{";
  payload += "\"temp_1\":" + String(temp1, 2) + ",";
  payload += "\"hum_1\":" + String(hum1, 2) + ",";
  payload += "\"temp_2\":" + String(temp2, 2) + ",";
  payload += "\"hum_2\":" + String(hum2, 2) + ",";
  payload += "\"raw_adc\":" + String(latestRawAdc) + ",";
  payload += "\"weight\":" + String(finalStableWeight, 2) + ",";
  payload += "\"hardening_progress\":" + String(hardeningProgress()) + ",";
  payload += "\"rfid_uid\":\"" + lastRfidUid + "\"";
  payload += "}";

  http.POST(payload);
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(250);

  Wire.begin(I2C1_SDA, I2C1_SCL);
  Wire1.begin(I2C2_SDA, I2C2_SCL);
  SPI.begin(SCK_PIN, MISO_PIN, MOSI_PIN, SS_PIN);

  mfrc522 = new MFRC522(SS_PIN, RST_PIN);
  am2320_1 = new Adafruit_AM2320(&Wire);
  am2320_2 = new Adafruit_AM2320(&Wire1);
  nau = new Adafruit_NAU7802();

  mfrc522->PCD_Init();
  byte rfidVersion = mfrc522->PCD_ReadRegister(mfrc522->VersionReg);
  rfidFound = (rfidVersion != 0x00 && rfidVersion != 0xFF);

  am1Found = am2320_1->begin();
  am2Found = am2320_2->begin();

  if (nau->begin(&Wire)) {
    nauFound = true;
    nau->setLDO(NAU7802_3V3);
    nau->setGain(NAU7802_GAIN_128);
    nau->setRate(NAU7802_RATE_10SPS);
    nau->calibrate(NAU7802_CALMOD_INTERNAL);
    nau->calibrate(NAU7802_CALMOD_OFFSET);
    delay(1000);
    tareScale();
  }

  connectWiFi();
  lastWeightChangeTime = millis();
}

void loop() {
  readWeightFilter();

  bool forceUpdate = false;
  bool bypassThrottle = false;

  // 1. Check for new RFID
  String scanned = readRfidUid();
  if (scanned.length() > 0 && scanned != lastRfidUid) {
    lastRfidUid = scanned;
    forceUpdate = true;
    bypassThrottle = true; // Send immediately, no matter what
  }

  // 2. Check for Major Weight Jumps (Spool added or removed)
  // If the jump is under 200g, it will just wait for the normal 5-second heartbeat
  if (fabs(emaWeight - lastPostedWeight) > 200.0) {
    forceUpdate = true;
  }

  unsigned long timeSinceLastPost = millis() - lastPostMs;

  // Post to server if:
  // - New RFID scanned (bypasses throttle completely)
  // - Weight jumped 200g+ AND 1 second has passed (prevents DDoS while scale bounces)
  // - 5 seconds have passed (standard idle heartbeat)
  if (bypassThrottle || (forceUpdate && timeSinceLastPost >= 1000) || timeSinceLastPost >= 5000) {
    lastPostMs = millis();
    lastPostedWeight = emaWeight; // Record what we are about to send to the server

    float temp1 = am1Found ? am2320_1->readTemperature() : NAN;
    float hum1 = am1Found ? am2320_1->readHumidity() : NAN;
    float temp2 = am2Found ? am2320_2->readTemperature() : NAN;
    float hum2 = am2Found ? am2320_2->readHumidity() : NAN;

    if (isnan(temp1)) temp1 = 0;
    if (isnan(hum1)) hum1 = 0;
    if (isnan(temp2)) temp2 = 0;
    if (isnan(hum2)) hum2 = 0;

    postTelemetry(temp1, hum1, temp2, hum2);
  }

  // Handle Serial Commands
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();

    if (cmd == "TARE") {
      tareScale();
      Serial.println("{\"status\":\"tared\"}");
    } else if (cmd == "WEIGHT") {
      Serial.print("{\"weight\":");
      Serial.print(finalStableWeight, 2);
      Serial.println("}");
    } else if (cmd == "ENV") {
      float temp1 = am1Found ? am2320_1->readTemperature() : 0;
      float hum1 = am1Found ? am2320_1->readHumidity() : 0;
      Serial.print("{\"temp\":");
      Serial.print(temp1, 2);
      Serial.print(",\"hum\":");
      Serial.print(hum1, 2);
      Serial.println("}");
    }
  }
}
'''

    return (
        template.replace("__WIFI_SSID__", _escape_cpp_string(ssid))
        .replace("__WIFI_PASSWORD__", _escape_cpp_string(password))
        .replace("__SERVER_URL__", _escape_cpp_string(server_url))
    )
