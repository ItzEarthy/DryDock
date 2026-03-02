# DryDock

DryDock is an ESP32-S3 based 3D printer filament inventory and environmental monitor. It connects physical filament spools to a Spoolman database using RFID and a load cell, while monitoring the health of the dry box silica gel.

## Features
* **Differential Humidity:** Compares internal dry box humidity against ambient room humidity. If the delta drops below 10%, the RGB LED turns red to indicate the silica gel needs replacing.
* **Auto-Weighing:** Uses a 5kg load cell and HX711 to weigh spools.
* **Spoolman Integration:** Scans an NFC tag attached to a spool, weighs it, and sends an HTTP PATCH request to update the remaining weight in Spoolman.

## Hardware
* ESP32-S3 Development Board
* 2x AM2320 Temperature/Humidity Sensors
* 1x 5kg Load Cell with HX711 Amplifier
* 1x [MFRC522 RFID/NFC](https://github.com/ItzEarthy/DryDock/blob/main/sensors/RFID-RC522.md) Reader (13.56MHz)
* 1x RGB LED (Common Cathode)
* 4x 10k Ohm Resistors (Pull-ups for the AM2320s)



**Note on the AM2320s:** These sensors have a fixed I2C address (0x5C). The code configures two separate hardware I2C buses (`Wire` and `Wire1`) on the ESP32-S3 so they don't conflict. 

## Usage
* Idle State: The system monitors humidity. The LED is green if the silica gel is good, red if saturated.
* Scan: Tap an NFC-tagged spool to the RC522 reader. The LED turns blue.
* Weigh: Place the spool on the load cell. The ESP32 calculates the average weight.
* Sync: The system sends the data to your local Spoolman instance and returns to the idle state.
