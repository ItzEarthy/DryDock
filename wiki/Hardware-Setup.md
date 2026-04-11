# Hardware Setup

This page covers the full bill of materials, how each component works, and exactly how to wire everything together.

## Bill of Materials

| Component | Quantity | Notes |
|---|---|---|
| ESP32-S3 Development Board | 1 | The firmware is written for the ESP32-S3. Other ESP32 variants are selectable at install time but the S3 is the primary target. |
| NAU7802 24-bit ADC Breakout (Adafruit) | 1 | Used to read the load cell with high precision. |
| 5 kg Load Cell | 1 | A standard half-bridge or full-bridge load cell rated for 5 kg. |
| AM2320 Temperature and Humidity Sensor | 2 | One goes inside the dry box; one monitors ambient room conditions. |
| MFRC522 RFID Reader Module | 1 | Reads 13.56 MHz NFC/RFID tags. |
| NFC Tags (13.56 MHz, NTAG213 or compatible) | 1 per spool | Attach one to each filament spool you want to track. |
| 10k Ohm Resistor | 4 | Pull-up resistors for the I2C lines of the two AM2320 sensors. |
| Breadboard or custom PCB | 1 | For prototyping the connections. |
| Jumper wires | As needed | |

## Component Overview

### NAU7802 24-bit ADC

The Adafruit NAU7802 breakout is a high-resolution analog-to-digital converter specifically designed for load cell applications. It communicates over **I2C** and provides a 24-bit reading of the differential voltage produced by the load cell. The firmware reads this value, subtracts the tare offset (set when the scale is empty), and divides by a calibration multiplier to produce a weight in grams.

The NAU7802 shares the first I2C bus (`Wire`) with **AM2320 sensor #1**. Both devices operate correctly on the same bus because they have different I2C addresses.

### AM2320 Sensors

The AM2320 is a low-cost, accurate combined temperature and humidity sensor. It communicates over **I2C** at a fixed address of `0x5C`. Because both sensors share the same fixed address, they **cannot be placed on the same I2C bus**. The firmware solves this by using the two independent hardware I2C controllers built into the ESP32-S3:

- **AM2320 #1** (inside the dry box) connects to `Wire` (I2C bus 1) on GPIO 4 and GPIO 5.
- **AM2320 #2** (outside, measuring ambient) connects to `Wire1` (I2C bus 2) on GPIO 8 and GPIO 9.

Each AM2320's SDA and SCL lines require a **10k ohm pull-up resistor** connected to the 3.3 V rail. Without these, the I2C bus will not function reliably.

### MFRC522 RFID Reader

The MFRC522 module reads 13.56 MHz RFID and NFC tags. It communicates via **SPI**. When a spool is tapped to the reader, the firmware captures the unique tag UID (a hexadecimal string such as `A1B2C3D4`) and immediately sends a telemetry update to the backend, which uses the UID to look up the matching spool in Spoolman.

**Important:** The MFRC522 operates at **3.3 V**. Do not connect its VCC pin to a 5 V supply, as this will damage the module. Always double-check the voltage label on the pin header before applying power.

## Pin Layout

All pin numbers refer to the GPIO numbers on the ESP32-S3 development board.

### MFRC522 RFID Reader (SPI)

| Module Pin | Connect to |
|---|---|
| VCC | 3.3 V |
| GND | GND |
| RST | GPIO 1 |
| IRQ | Not connected (optional interrupt, not used by the firmware) |
| MISO | GPIO 13 |
| MOSI | GPIO 11 |
| SCK | GPIO 12 |
| SDA (SS) | GPIO 10 |

### AM2320 Sensor #1 - Inside the Dry Box (I2C Bus 1, `Wire`)

| Module Pin | Connect to |
|---|---|
| VDD | 3.3 V |
| GND | GND |
| SDA | GPIO 4, with a 10k pull-up to 3.3 V |
| SCL | GPIO 5, with a 10k pull-up to 3.3 V |

### AM2320 Sensor #2 - Ambient / Outside (I2C Bus 2, `Wire1`)

| Module Pin | Connect to |
|---|---|
| VDD | 3.3 V |
| GND | GND |
| SDA | GPIO 8, with a 10k pull-up to 3.3 V |
| SCL | GPIO 9, with a 10k pull-up to 3.3 V |

### NAU7802 24-bit ADC (I2C Bus 1, shared with AM2320 #1)

| Module Pin | Connect to |
|---|---|
| VIN | 3.3 V |
| GND | GND |
| SDA | GPIO 4 (shared with AM2320 #1) |
| SCL | GPIO 5 (shared with AM2320 #1) |
| AV | Not connected |
| DRDY | Not connected |

The load cell wires connect directly to the NAU7802 breakout board's differential input terminals according to the Adafruit NAU7802 guide.

## I2C Bus Summary

| Bus | GPIO Pins | Devices |
|---|---|---|
| `Wire` (I2C bus 1) | SDA: GPIO 4, SCL: GPIO 5 | NAU7802 ADC, AM2320 #1 (inside) |
| `Wire1` (I2C bus 2) | SDA: GPIO 8, SCL: GPIO 9 | AM2320 #2 (ambient) |

## SPI Bus Summary

| Signal | GPIO Pin |
|---|---|
| SCK | GPIO 12 |
| MISO | GPIO 13 |
| MOSI | GPIO 11 |
| SS (SDA) | GPIO 10 |
| RST | GPIO 1 |

## Wiring Notes

- Use short, neat wiring runs especially for the load cell, as long wires can introduce noise into the ADC reading.
- The pull-up resistors for the AM2320 sensors should be placed as close to the sensor as possible.
- If you notice inconsistent RFID reads, ensure the SPI wires are not running parallel to the I2C or load cell wires, as this can cause interference.
- All logic in the system runs at **3.3 V**. Do not use 5 V logic signals on any of the GPIO pins.

## Preparing NFC Tags

Any 13.56 MHz NFC tag (NTAG213, NTAG215, NTAG216, or compatible MIFARE cards) will work. The system only reads the tag's fixed UID - it does not write any data to the tag. You do not need to pre-program the tags in any way. Simply attach one to each filament spool (a small piece of double-sided tape works well) and then scan it in the DryDock dashboard to link it to a Spoolman spool record.
