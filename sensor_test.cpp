#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <Adafruit_AM2320.h>
#include <Adafruit_NAU7802.h>

// --- RFID Pins ---
#define RST_PIN 1
#define SS_PIN  10
#define SCK_PIN 12
#define MISO_PIN 13
#define MOSI_PIN 11

// --- I2C Pins ---
#define I2C1_SDA 4
#define I2C1_SCL 5
#define I2C2_SDA 8
#define I2C2_SCL 9

// --- Objects ---
MFRC522 mfrc522(SS_PIN, RST_PIN);
TwoWire I2Cone = TwoWire(0); // First I2C bus
TwoWire I2Ctwo = TwoWire(1); // Second I2C bus

Adafruit_AM2320 am2320_1(&I2Cone);
Adafruit_AM2320 am2320_2(&I2Ctwo);
Adafruit_NAU7802 nau;

unsigned long lastSensorRead = 0;

void setup() {
  Serial.begin(115200);
  while (!Serial) { delay(10); } // Wait for Serial Monitor to open
  Serial.println("Starting ESP32-S3 Hardware Test...");

  // 1. Initialize custom I2C Buses
  I2Cone.begin(I2C1_SDA, I2C1_SCL);
  I2Ctwo.begin(I2C2_SDA, I2C2_SCL);

  // 2. Initialize custom SPI for RFID
  SPI.begin(SCK_PIN, MISO_PIN, MOSI_PIN, SS_PIN);
  mfrc522.PCD_Init();
  Serial.println("RFID reader initialized.");

  // 3. Initialize AM2320 #1
  if (!am2320_1.begin()) {
    Serial.println("Error: AM2320 #1 not found on Bus 1!");
  } else {
    Serial.println("AM2320 #1 initialized.");
  }

  // 4. Initialize AM2320 #2
  if (!am2320_2.begin()) {
    Serial.println("Error: AM2320 #2 not found on Bus 2!");
  } else {
    Serial.println("AM2320 #2 initialized.");
  }

  // 5. Initialize NAU7802 on Bus 1
  if (!nau.begin(&I2Cone)) {
    Serial.println("Error: NAU7802 not found on Bus 1!");
  } else {
    Serial.println("NAU7802 initialized.");
  }
}

void loop() {
  // Poll for RFID cards constantly
  if (mfrc522.PICC_IsNewCardPresent() && mfrc522.PICC_ReadCardSerial()) {
    Serial.print("\nRFID Card Detected! UID:");
    for (byte i = 0; i < mfrc522.uid.size; i++) {
      Serial.print(mfrc522.uid.uidByte[i] < 0x10 ? " 0" : " ");
      Serial.print(mfrc522.uid.uidByte[i], HEX);
    }
    Serial.println();
    mfrc522.PICC_HaltA(); // Stop reading to avoid spam
  }

  // Read I2C sensors every 2 seconds
  if (millis() - lastSensorRead > 2000) {
    lastSensorRead = millis();
    
    Serial.println("\n--- Sensor Readings ---");

    Serial.print("AM2320 #1 -> Temp: ");
    Serial.print(am2320_1.readTemperature());
    Serial.print(" C, Hum: ");
    Serial.print(am2320_1.readHumidity());
    Serial.println(" %");

    Serial.print("AM2320 #2 -> Temp: ");
    Serial.print(am2320_2.readTemperature());
    Serial.print(" C, Hum: ");
    Serial.print(am2320_2.readHumidity());
    Serial.println(" %");

    if (nau.available()) {
      Serial.print("NAU7802   -> Raw ADC: ");
      Serial.println(nau.read());
    } else {
      Serial.println("NAU7802   -> Not available/ready");
    }
  }
}
