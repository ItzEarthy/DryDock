#include <SPI.h>
#include <MFRC522.h>
#include <Wire.h>
#include <Adafruit_AM2320.h>
#include <Adafruit_NAU7802.h>

#define RST_PIN 1
#define SS_PIN  10
#define SCK_PIN 12
#define MISO_PIN 13
#define MOSI_PIN 11

#define I2C1_SDA 4
#define I2C1_SCL 5
#define I2C2_SDA 8
#define I2C2_SCL 9

// --- ADVANCED ACCURACY SETTINGS ---
float emaWeight = 0.0;
const float EMA_ALPHA = 0.2; // 0.0 to 1.0. Lower = smoother but slower to react.

float finalStableWeight = 0.0;
unsigned long lastWeightChangeTime = 0;
const float SETTLE_THRESHOLD = 3.0;         // Grams of change required to trigger a new reading
const unsigned long SETTLE_DELAY_MS = 4000; // Wait 4 seconds for aluminum creep to stop

// --- WEIGHT CALIBRATION ---
// We will figure out this number next! Leave it at 1.0 for now.
float calibrationFactor = 426.75; 
int32_t zeroOffset = 0;

MFRC522* mfrc522;
Adafruit_AM2320* am2320_1;
Adafruit_AM2320* am2320_2;
Adafruit_NAU7802* nau;

unsigned long lastSensorRead = 0;

bool rfidFound = false;
bool am1Found  = false;
bool am2Found  = false;
bool nauFound  = false;

void setup() {
  Serial.begin(115200);
  while (!Serial) { delay(10); } 
  Serial.println("\nStarting ESP32-S3 Hardware Test...");

  Wire.begin(I2C1_SDA, I2C1_SCL);
  Wire1.begin(I2C2_SDA, I2C2_SCL);
  SPI.begin(SCK_PIN, MISO_PIN, MOSI_PIN, SS_PIN);

  mfrc522 = new MFRC522(SS_PIN, RST_PIN);
  am2320_1 = new Adafruit_AM2320(&Wire);
  am2320_2 = new Adafruit_AM2320(&Wire1);
  nau = new Adafruit_NAU7802();

  // 1. RFID
  mfrc522->PCD_Init();
  byte rfidVersion = mfrc522->PCD_ReadRegister(mfrc522->VersionReg);
  rfidFound = (rfidVersion != 0x00 && rfidVersion != 0xFF);

  // 2. AM2320s
  am1Found = am2320_1->begin();
  am2Found = am2320_2->begin();

  // 3. NAU7802 Weight Sensor
  // 3. NAU7802 Weight Sensor
  if (nau->begin(&Wire)) {
    nauFound = true;
    Serial.println("NAU7802 found. Configuring...");
    
    // Configure the sensor for standard load cell usage
    nau->setLDO(NAU7802_3V3);           // Stable 3.3V excitation
    nau->setGain(NAU7802_GAIN_128);     // Standard gain for small signals
    nau->setRate(NAU7802_RATE_10SPS);   // 10 Samples Per Second (slower = less noise)
    
    // Run internal calibration
    nau->calibrate(NAU7802_CALMOD_INTERNAL);
    nau->calibrate(NAU7802_CALMOD_OFFSET);

    Serial.println("Taring scale...");
    delay(1000); 

    // Average 10 readings for a solid zero point
    int32_t tareSum = 0;
    for (int i = 0; i < 10; i++) {
      while (!nau->available()) { delay(1); } // Wait for reading
      tareSum += nau->read();
    }
    zeroOffset = tareSum / 10;
    
    Serial.print("Scale zeroed at: ");
    Serial.println(zeroOffset);
  } else {
    Serial.println("NAU7802 missing! Check I2C wiring.");
    nauFound = false; 
  }
}

void loop() {
  // 1. Keep filtering in the background silently
  if (millis() - lastSensorRead > 100) {
    lastSensorRead = millis();
    
    if (nauFound && nau->available()) {
      int32_t currentReading = nau->read();
      float rawWeight = (currentReading - zeroOffset) / calibrationFactor;

      if (abs(rawWeight - emaWeight) > 50.0) {
        emaWeight = rawWeight;
      } else {
        emaWeight = (EMA_ALPHA * rawWeight) + ((1.0 - EMA_ALPHA) * emaWeight);
      }
    }
  }

  // 2. Listen for commands from the Pi
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();

    if (cmd == "WEIGHT") {
      Serial.print("{\"weight\": "); 
      Serial.print(emaWeight, 1); 
      Serial.println("}");
    } 
    else if (cmd == "ENV") {
      if (am1Found) {
        Serial.print("{\"temp\": "); Serial.print(am2320_1->readTemperature());
        Serial.print(", \"hum\": "); Serial.print(am2320_1->readHumidity()); Serial.println("}");
      } else {
        Serial.println("{\"error\": \"AM2320 missing\"}");
      }
    }
    else if (cmd == "TARE") {
      int32_t tareSum = 0;
      for (int i = 0; i < 10; i++) {
        while (!nau->available()) { delay(1); }
        tareSum += nau->read();
      }
      zeroOffset = tareSum / 10;
      emaWeight = 0.0;
      Serial.println("{\"status\": \"tared\"}");
    }
    else {
      Serial.println("{\"error\": \"Unknown command\"}");
    }
  }
}