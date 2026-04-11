# DryDock Wiki

Welcome to the official DryDock documentation. This wiki covers everything you need to know to build, install, configure, and use the DryDock filament storage and inventory system.

## What is DryDock?

DryDock is an open-source smart filament management system for 3D printing. It combines a physical hardware unit with a web-based dashboard to give you real-time insight into the condition of your filament and dry storage environment.

The system uses an **ESP32 microcontroller** to continuously read data from three types of sensors:

- A **NAU7802 24-bit ADC** connected to a load cell, which weighs filament spools with precision.
- Two **AM2320 temperature and humidity sensors** - one placed inside the dry box and one measuring ambient room conditions. The difference between these two readings tells you whether your desiccant (silica gel) is still effective.
- An **MFRC522 RFID reader** that scans NFC tags attached to your spools, allowing the system to identify exactly which spool is being weighed.

The ESP32 reports all of this data over Wi-Fi to a **Python/Flask backend** running on a Raspberry Pi (or any Linux host on the same network). The backend stores the data, provides the dashboard, and integrates with **Spoolman** to keep your filament inventory automatically up to date.

## Key Features

- **Differential Humidity Monitoring:** Compares inside and outside humidity to determine desiccant health. Alerts you when the humidity delta drops below your configured threshold.
- **Automatic Spool Weighing:** Uses a high-resolution 24-bit ADC and a 5 kg load cell to measure remaining filament weight.
- **RFID Spool Identification:** Tap an NFC-tagged spool to the reader and the system knows exactly which spool it is weighing.
- **Spoolman Integration:** Automatically updates remaining filament weight in your Spoolman database after each scan and weigh cycle.
- **Historical Charts:** The dashboard stores and displays sensor history for the last hour, 24 hours, or 7 days.
- **Scale Calibration:** A built-in calibration wizard guides you through taring the scale and computing a calibration multiplier using a known reference weight.
- **Automated Backups:** The SQLite database is backed up on a configurable schedule.
- **Log Retention:** Sensor logs are automatically pruned after a configurable number of days to prevent the database from growing indefinitely.
- **Firmware Generator:** The web UI generates a ready-to-flash `.ino` firmware file with your Wi-Fi credentials and server address injected automatically.

## Wiki Pages

| Page | Description |
|---|---|
| [Hardware Setup](Hardware-Setup) | Bill of materials, wiring diagrams, and pin assignments |
| [Software Installation](Software-Installation) | Installing the backend on a Raspberry Pi |
| [Firmware Setup](Firmware-Setup) | Generating and flashing the ESP32 firmware |
| [Configuration](Configuration) | Environment variables, settings page, and Spoolman integration |
| [Using DryDock](Using-DryDock) | Dashboard walkthrough, spool scanning workflow, and calibration |
| [API Reference](API-Reference) | Complete REST API documentation |
| [Troubleshooting](Troubleshooting) | Solutions to common problems |

## Quick Start Summary

1. Assemble the hardware following the [Hardware Setup](Hardware-Setup) guide.
2. Clone the repository onto your Raspberry Pi and run `install.sh` as described in [Software Installation](Software-Installation).
3. Open the dashboard in a browser and use the built-in firmware generator to create your `DryDock.ino` file.
4. Flash the firmware to your ESP32 as described in [Firmware Setup](Firmware-Setup).
5. Calibrate the scale using the Calibration section of the dashboard.
6. Start scanning spools.
