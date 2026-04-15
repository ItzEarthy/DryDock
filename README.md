<img src="https://github.com/ItzEarthy/DryDock/blob/main/static/Dry_dock.svg" width="200"> 

# DryDock 

[![License](https://img.shields.io/github/license/ItzEarthy/DryDock)](https://github.com/ItzEarthy/DryDock/blob/main/LICENSE)
[![Stars](https://img.shields.io/github/stars/ItzEarthy/DryDock?style=flat)](https://github.com/ItzEarthy/DryDock/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/ItzEarthy/DryDock)](https://github.com/ItzEarthy/DryDock/commits/main)
[![Issues](https://img.shields.io/github/issues/ItzEarthy/DryDock)](https://github.com/ItzEarthy/DryDock/issues)
[![Release](https://img.shields.io/github/v/release/ItzEarthy/DryDock?include_prereleases)](https://github.com/ItzEarthy/DryDock/releases)
[![Wiki](https://img.shields.io/badge/wiki-docs-blue)](https://github.com/ItzEarthy/DryDock/wiki)

**Smart filament storage and inventory management for 3D printing.**

<img width="50%" height="587" alt="DryDock dashboard screenshot" src="https://github.com/user-attachments/assets/1a7363a9-2371-4622-832a-392946b3dc50" />

DryDock is a web dashboard that gives you real-time visibility into your filament supply and dry box environment. It tracks remaining filament weight per spool, monitors temperature and humidity inside and outside the dry box, and integrates with popular 3D-printing tooling to keep your inventory accurate with minimal manual work.

---

## Key Features

- **Real-time weight tracking**  
  A 24-bit NAU7802 ADC and a 5 kg load cell measure remaining filament weight with high precision. A built-in calibration wizard makes setup straightforward.

- **Temperature and humidity monitoring**  
  Dual AM2320 sensors measure conditions inside and outside the dry box. DryDock computes the humidity differential so you can tell whether your desiccant is still doing its job.

  <img width="50%" height="557" alt="image" src="https://github.com/user-attachments/assets/a7ca87c8-0efc-4d99-ba94-15a0c963b0f1" />

- **RFID spool identification**  
  An MFRC522 reader scans 13.56 MHz NFC tags attached to spools, so DryDock knows exactly which spool is being weighed—no manual selection needed.

- **Spoolman integration**  
  After each scan-and-weigh cycle, DryDock can automatically update the remaining weight in your Spoolman database over the local network.

  <img width="50%" height="761" alt="image" src="https://github.com/user-attachments/assets/84511037-312d-45ba-86b2-ad547beb3129" />


- **Klipper / Moonraker integration**  
  DryDock can be registered with Moonraker’s Update Manager, allowing updates directly from Mainsail or Fluidd.

- **Local web dashboard**  
  A browser-based interface shows live sensor readings, historical charts (1 hour / 24 hours / 7 days), scale calibration, firmware generation, and system settings.

---

## Requirements

- A running **Spoolman** instance (on your network)
- A **Debian-based** machine running **Klipper** (commonly a Raspberry Pi)

---

## Hardware Overview

The following core components are required to build a DryDock unit:

| Component | Purpose |
|---|---|
| ESP32 (S3 recommended) | Main microcontroller; reads sensors and reports data over Wi-Fi |
| NAU7802 24-bit ADC | High-resolution load cell amplifier for weight measurement |
| AM2320 (x2) | Temperature and humidity sensors (inside + outside the dry box) |
| MFRC522 | 13.56 MHz RFID/NFC reader for spool identification |
| 5 kg load cell | Measures spool weight |
| RGB LED | Visual status indicator |

**Data flow (high level):**  
`[ESP32 + Sensors] --(Wi‑Fi/JSON)--> [DryDock Web Server] <---> [Spoolman / Klipper]`

Full wiring diagrams, pin assignments, and a complete bill of materials are available in the wiki:
- **Hardware Setup:** https://github.com/ItzEarthy/DryDock/wiki/2.-Hardware-Setup

### Current Setup

The current setup uses a breadboard and jumper cables. A PCB and 3D-printed hardware are in the works.

<img width="50%" height="" alt="Full setup" src="https://github.com/user-attachments/assets/b90c60d8-83a0-453f-b617-299f309558df" />
<img width="50%" height="" alt="Part setup" src="https://github.com/user-attachments/assets/cd3a3084-eaff-4a72-9c14-993c97f4ee57" />

---

## Installation

Please see the **Software Installation** page on the wiki:
- https://github.com/ItzEarthy/DryDock/wiki/3.-Software-Installation

---

## Documentation

Full documentation is maintained in the **GitHub Wiki**:
- https://github.com/ItzEarthy/DryDock/wiki

| Wiki Page | Description |
|---|---|
| [Home](https://github.com/ItzEarthy/DryDock/wiki) | Project overview and quick-start summary |
| [Hardware Setup](https://github.com/ItzEarthy/DryDock/wiki/2.-Hardware-Setup) | Bill of materials, wiring diagrams, and pin assignments |
| [Software Installation](https://github.com/ItzEarthy/DryDock/wiki/3.-Software-Installation) | Installing the backend on a Raspberry Pi |
| [Firmware Setup](https://github.com/ItzEarthy/DryDock/wiki/4.-Firmware-Setup) | Generating and flashing the ESP32 firmware |
| [Configuration](https://github.com/ItzEarthy/DryDock/wiki/5.-Configuration) | Environment variables, settings page, and Spoolman integration |
| [Using DryDock](https://github.com/ItzEarthy/DryDock/wiki/6.-Using-DryDock) | Dashboard walkthrough, spool scanning workflow, and calibration |
| [API Reference](https://github.com/ItzEarthy/DryDock/wiki/7.-API-Reference) | Complete REST API documentation for the Flask backend |
| [Troubleshooting](https://github.com/ItzEarthy/DryDock/wiki/8.-Troubleshooting) | Solutions to common problems |

---

## Contributing

Contributions are welcome. If you find a bug, have a feature request, or want to improve the documentation, please open an issue or submit a pull request.

---

## License

This project is licensed under the **[LICENSE](LICENSE)** file.
