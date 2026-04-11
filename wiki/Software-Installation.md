# Software Installation

This guide walks you through installing the DryDock backend on a Raspberry Pi (or any Debian-based Linux host). The installer script handles most of the work for you.

## Prerequisites

Before you begin, make sure you have:

- A Raspberry Pi (any model with Wi-Fi, such as a Pi 3, Pi 4, or Pi Zero 2 W) running a recent version of **Raspberry Pi OS** (Bookworm or Bullseye recommended). Any Debian-based Linux system will also work.
- An active internet connection on the Pi.
- **Spoolman** already installed and running somewhere on your local network. DryDock integrates with Spoolman to manage your filament inventory. You can install Spoolman on the same Pi.
- A terminal open on the Pi (either directly or via SSH).

## Step 1 - Clone the Repository

Navigate to the directory where you want to install DryDock. The home directory is a good choice.

```bash
cd ~
git clone https://github.com/ItzEarthy/DryDock.git
cd DryDock
```

## Step 2 - Run the Installer

The `install.sh` script handles all system dependencies, the Python virtual environment, database setup, and the systemd service. Run it with:

```bash
bash install.sh
```

The script will guide you through a series of prompts. Each is explained below.

### Installer Prompts

**Wi-Fi Network Name**
Enter the SSID (name) of the Wi-Fi network your ESP32 will connect to. This value is stored in the `.env` file and will be injected into the firmware when you generate it from the dashboard.

**Wi-Fi Password**
Enter the Wi-Fi password. The input is hidden as you type. This is also stored in the `.env` file.

**Board Type**
Select your ESP32 board variant. The choices are:

```
1) Standard ESP32 (esp32dev)
2) ESP32-S3 (esp32-s3-devkitc-1)
3) ESP32-C3 (esp32-c3-devkitc-02)
```

If you are using an ESP32-S3 (the primary supported board), enter `2`.

**Klipper / Moonraker Integration**
If you run Klipper and Moonraker on the same Pi, you can add DryDock to Moonraker's update manager. This allows you to update DryDock from the Mainsail or Fluidd interface. If you are not using Klipper, enter `2` to skip this step.

### What the Installer Does

After you answer the prompts, the script performs the following steps automatically:

1. Installs system packages: `python3-venv`, `python3-pip`, `curl`, `git`, and `build-essential`.
2. Applies a linker fix needed on some Raspberry Pi models to allow PlatformIO to function correctly.
3. Downloads and installs PlatformIO udev rules so the Pi can detect and program ESP32 boards over USB without requiring root.
4. Adds your user to the `dialout` group (required for USB serial access).
5. Creates a Python virtual environment in a `.venv` directory inside the project folder.
6. Installs all Python dependencies: Flask, Flask-SQLAlchemy, Flask-Migrate, Werkzeug, APScheduler, requests, and PlatformIO.
7. Initializes and migrates the SQLite database.
8. Creates and enables a **systemd service** (`drydock.service`) so DryDock starts automatically on boot and restarts if it crashes.

When the script finishes, it prints:

```
=====================================================
             Installation Complete!
 Dashboard: http://<your-pi-ip>:5000
=====================================================
```

Open the printed URL in a browser on any device on the same network.

## Step 3 - Initial Account Setup

The first time you open the dashboard, you will be redirected to the **Setup** page. Create an administrator username and password. These credentials are required to log in and to access protected features such as settings, calibration, and firmware generation.

After submitting the form, you are logged in and taken to the main dashboard.

## Updating DryDock

To update to the latest version, pull the new code and re-run the installer with the `-f` flag. The `-f` flag runs the installer in "fix environment" mode, which only updates any missing or changed configuration values and re-applies the service without prompting for information that is already present.

```bash
cd ~/DryDock
git pull
bash install.sh -f
```

## Installer Flags

| Flag | Behavior |
|---|---|
| *(none)* | Full interactive installation |
| `-s` | Skip Wi-Fi prompts (useful if you have already set the credentials) |
| `-f` | Fix mode: only add missing `.env` entries and re-run service setup |
| `-sf` | Combine both flags |

## Managing the Service

The DryDock backend runs as a systemd service named `drydock`. Use the following commands to manage it:

**Check the service status:**
```bash
sudo systemctl status drydock
```

**View live logs:**
```bash
sudo journalctl -u drydock -f
```

**Restart the service:**
```bash
sudo systemctl restart drydock
```

**Stop the service:**
```bash
sudo systemctl stop drydock
```

**Disable autostart on boot:**
```bash
sudo systemctl disable drydock
```

## Python Virtual Environment

All Python dependencies are installed inside a `.venv` directory in the project folder. To activate the virtual environment manually (for example, to run Flask commands directly), use:

```bash
cd ~/DryDock
source .venv/bin/activate
```

You can then run Flask management commands such as:

```bash
export FLASK_APP=app.py
flask db upgrade
```

To exit the virtual environment, type `deactivate`.

## File Locations

| Path | Description |
|---|---|
| `~/DryDock/` | Project root directory |
| `~/DryDock/.env` | Environment variables (Wi-Fi credentials, board ID, server IP) |
| `~/DryDock/.venv/` | Python virtual environment |
| `~/DryDock/instance/drydock.db` | SQLite database |
| `~/DryDock/instance/logs/drydock.jsonl` | Structured event log |
| `/etc/systemd/system/drydock.service` | Systemd service definition |
