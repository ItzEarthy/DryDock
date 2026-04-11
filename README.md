# DryDock

**Smart filament storage and inventory management for 3D printing.**

DryDock is an open-source system that combines an ESP32-based hardware unit with a Python/Flask web dashboard to give you real-time visibility into your filament supply and dry box environment. It tracks remaining filament weight by spool, monitors the temperature and humidity inside your dry storage, and keeps your Spoolman inventory up to date automatically — all from a local web interface that integrates cleanly with Klipper and Moonraker.

---

## Key Features

- **Real-time Weight Tracking:** A 24-bit NAU7802 ADC and a 5 kg load cell measure remaining filament weight with high precision. A built-in calibration wizard makes setup straightforward.
- **Temperature and Humidity Monitoring:** Dual AM2320 sensors measure conditions inside and outside the dry box. The system computes the humidity differential to tell you whether your desiccant is still effective.
- **RFID Spool Identification:** An MFRC522 reader scans 13.56 MHz NFC tags attached to your spools. The system knows exactly which spool it is weighing without any manual input.
- **Spoolman Integration:** After each scan-and-weigh cycle, DryDock automatically updates the remaining weight in your Spoolman database over the local network.
- **Klipper and Moonraker Integration:** DryDock can be registered with Moonraker's update manager, letting you update it directly from Mainsail or Fluidd.
- **Local Web Dashboard:** A browser-based interface displays live sensor data, historical charts (1 hour, 24 hours, or 7 days), scale calibration, firmware generation, and system settings. No cloud services or external accounts required.

---

## Hardware Overview

The following core components are required to build a DryDock unit:

| Component | Purpose |
|---|---|
| ESP32 (S3 recommended) | Main microcontroller; reads sensors and reports data over Wi-Fi |
| NAU7802 24-bit ADC | High-resolution load cell amplifier for weight measurement |
| AM2320 (x2) | Temperature and humidity sensors for inside and outside the dry box |
| MFRC522 | 13.56 MHz RFID/NFC reader for spool identification |
| 5 kg Load Cell | Measures spool weight |
| RGB LED | Visual status indicator |

Full wiring diagrams, pin assignments, and a complete bill of materials are available in the [Hardware Setup](https://github.com/ItzEarthy/DryDock/wiki/Hardware-Setup) wiki page.

---

## Quick Start

The steps below are a brief summary. **For the complete, step-by-step guide, see the [GitHub Wiki](https://github.com/ItzEarthy/DryDock/wiki).**

1. **Clone the repository** onto your Raspberry Pi (or any Debian-based Linux host):
   ```bash
   git clone https://github.com/ItzEarthy/DryDock.git
   cd DryDock
   ```

2. **Run the installer.** The `install.sh` script sets up all dependencies, the Python environment, the SQLite database, and a systemd service:
   ```bash
   bash install.sh
   ```

3. **Open the dashboard** in a browser at `http://<your-pi-ip>:5000` and complete the initial account setup.

4. **Generate and flash the firmware.** Use the dashboard's built-in firmware generator to produce a pre-configured `.ino` file, then flash it to your ESP32 using `build_esp32.sh`.

> **Note:** The steps above omit important details around hardware assembly, board selection, Spoolman configuration, and scale calibration. Follow the Wiki for the full walkthrough before attempting setup.

---

## Documentation

Full documentation is maintained in the **[GitHub Wiki](https://github.com/ItzEarthy/DryDock/wiki)**. The pages below cover every stage of setup and use:

| Wiki Page | Description |
|---|---|
| [Home](https://github.com/ItzEarthy/DryDock/wiki) | Project overview and quick-start summary |
| [Hardware Setup](https://github.com/ItzEarthy/DryDock/wiki/Hardware-Setup) | Bill of materials, wiring diagrams, and pin assignments |
| [Software Installation](https://github.com/ItzEarthy/DryDock/wiki/Software-Installation) | Installing the backend on a Raspberry Pi |
| [Firmware Setup](https://github.com/ItzEarthy/DryDock/wiki/Firmware-Setup) | Generating and flashing the ESP32 firmware |
| [Configuration](https://github.com/ItzEarthy/DryDock/wiki/Configuration) | Environment variables, settings page, and Spoolman integration |
| [Using DryDock](https://github.com/ItzEarthy/DryDock/wiki/Using-DryDock) | Dashboard walkthrough, spool scanning workflow, and calibration |
| [API Reference](https://github.com/ItzEarthy/DryDock/wiki/API-Reference) | Complete REST API documentation for the Flask backend |
| [Troubleshooting](https://github.com/ItzEarthy/DryDock/wiki/Troubleshooting) | Solutions to common problems |

---

## Contributing

Contributions are welcome. If you find a bug, have a feature request, or want to improve the documentation, please open an issue or submit a pull request. When contributing code, please follow the existing style and include a clear description of your changes.

---

## License

This project is licensed under the [Insert License Here]. See the `LICENSE` file for details.
