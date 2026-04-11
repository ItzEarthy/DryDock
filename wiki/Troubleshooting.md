# Troubleshooting

This page covers the most common problems encountered during installation and daily use of DryDock, along with their solutions.

---

## ESP32 Shows as Offline on the Dashboard

**Symptom:** The ESP32 status badge on the dashboard shows **Offline**, and no live sensor readings appear.

**Causes and solutions:**

**1. The ESP32 has not connected to Wi-Fi.**
Open the Arduino Serial Monitor at 115200 baud immediately after the ESP32 boots. If you do not see a Wi-Fi connection message and the telemetry begins posting, the Wi-Fi credentials may be incorrect. Re-generate the firmware from the dashboard with the correct SSID and password, re-upload it, and try again.

**2. The ESP32 is on a different network than the Raspberry Pi.**
The ESP32 sends HTTP POST requests to the backend IP and port stored in the firmware. Both devices must be on the same local network subnet. Confirm the IP address in the generated firmware matches the actual current IP of the Raspberry Pi. Re-generate the firmware if the Pi's IP address has changed.

**3. The DryDock service is not running.**
Check the service status on the Pi:

```bash
sudo systemctl status drydock
```

If it is not running, start it:

```bash
sudo systemctl start drydock
```

View recent error messages with:

```bash
sudo journalctl -u drydock -n 50
```

**4. The backend port is blocked by a firewall.**
By default, DryDock runs on port `5000`. If your Pi has a firewall enabled (such as `ufw`), make sure port 5000 is allowed:

```bash
sudo ufw allow 5000/tcp
```

**5. Telemetry is stale.**
The backend considers the ESP32 offline if no update has been received in the last **3 minutes**. If the ESP32 is powered but not posting frequently, check for Wi-Fi connectivity issues. A freshly powered ESP32 may take up to 12 seconds to join the Wi-Fi network before it begins posting.

---

## Weight Reads as Zero or Nonsensical Values

**Symptom:** The weight panel shows 0 grams when a heavy spool is on the scale, or the value fluctuates wildly and does not settle.

**Causes and solutions:**

**1. The scale has not been tared.**
If the load cell has shifted or the Pi was rebooted, the tare offset may no longer match the current empty-scale reading. Remove everything from the load cell and click **Tare** in the calibration panel on the dashboard.

**2. The calibration multiplier is incorrect.**
After taring, perform a single-point calibration using a known reference weight to re-establish the multiplier. See [Using DryDock - Scale Calibration](Using-DryDock#scale-calibration) for the procedure.

**3. The NAU7802 is not detected.**
If the NAU7802 is not initialized at startup, the firmware will skip all weight-related code and post `raw_adc: 0` in every telemetry update. Check that:
- The SDA and SCL wires are connected to GPIO 4 and GPIO 5 respectively.
- The 3.3 V power supply is connected.
- The NAU7802 module is not damaged.

Open the Arduino Serial Monitor and send the `WEIGHT` command to see the raw response. If the ESP32 reports `0.00`, the sensor was not found.

**4. The load cell wires are connected incorrectly to the NAU7802.**
Load cells typically have four wires: red (+Excitation), black (-Excitation), white (+Signal), and green (-Signal). Swapping the signal wires will cause the scale to read negative values. Refer to the Adafruit NAU7802 documentation for the correct terminal mapping.

**5. Values below 8 grams are shown as zero.**
This is intentional. DryDock treats readings at or below 8 grams as zero to filter out noise on the empty platform. This threshold is called the **auto-zero** threshold and is not configurable through the UI.

---

## Humidity Readings Show Identical Values

**Symptom:** Both the inside and ambient humidity readings are the same, or one always reads zero.

**Causes and solutions:**

**1. Both AM2320 sensors are on the same I2C bus.**
The AM2320 has a fixed I2C address (`0x5C`). If both sensors are connected to the same `SDA`/`SCL` pair, they will conflict and produce incorrect readings. AM2320 #1 must be on GPIO 4/5 and AM2320 #2 must be on GPIO 8/9 as described in the [Hardware Setup](Hardware-Setup) guide.

**2. The pull-up resistors are missing.**
Each AM2320 sensor requires a 10k ohm pull-up resistor on both its SDA and SCL lines. Without these, the I2C communication will fail intermittently or not at all.

**3. One sensor is not detected.**
If one AM2320 fails to initialize, the firmware substitutes `0` for its readings. Check the wiring and power supply for that sensor.

---

## Spoolman Connection Fails

**Symptom:** The Spoolman status badge shows a connection error, or syncing a spool fails.

**Causes and solutions:**

**1. The Spoolman URL is incorrect.**
Verify the URL in DryDock Settings. Common mistakes include forgetting `http://`, using the wrong port, or including a trailing path segment. The URL should end at the port number with no trailing slash. Example: `http://192.168.1.55:7912`.

Use **Test Connection** on the Settings page to check before saving.

**2. Spoolman is not running.**
Confirm that Spoolman is running on the target host. If you are using Docker, check the container status:

```bash
docker ps | grep spoolman
```

**3. The Pi cannot reach the Spoolman host.**
If Spoolman runs on a different machine, confirm both are on the same network and there is no firewall blocking the Spoolman port.

---

## RFID Tags Are Not Being Read

**Symptom:** No RFID UID appears in the dashboard even when a tag is held against the reader.

**Causes and solutions:**

**1. The MFRC522 is not receiving 3.3 V.**
Verify that the VCC pin is connected to 3.3 V and not 5 V. Supplying 5 V to the MFRC522 will damage it.

**2. SPI pins are wired incorrectly.**
Double-check every SPI pin against the [Hardware Setup](Hardware-Setup) pin table. The MFRC522 uses a custom SPI initialization in the firmware; pin labels on the physical module may differ from manufacturer to manufacturer. **Always use the labels printed on the module board itself.**

**3. The tag is the wrong frequency.**
DryDock only supports **13.56 MHz** tags (NFC / ISO 14443). Lower-frequency tags (125 kHz, commonly used for access cards) will not be read by the MFRC522.

**4. The tag is being held too far from the reader.**
The MFRC522 has a typical read range of about 3 to 5 centimeters. Hold the tag flat and close to the reader coil.

---

## The Installation Script Fails

**Symptom:** `install.sh` exits with an error before completing.

**Causes and solutions:**

**1. `python3-venv` is not available.**
On some minimal Pi OS images, the `venv` package must be installed separately. The script does this automatically, but if `apt` fails, try running manually:

```bash
sudo apt update
sudo apt install python3-venv python3-pip -y
```

**2. USB permission error when flashing.**
If the PlatformIO upload fails with a permission denied error on the serial port, the `dialout` group change made by the installer requires you to **log out and log back in** before it takes effect. After re-logging in, try the flash again.

**3. The Pi linker fix was not applied.**
On some Raspberry Pi models, PlatformIO's ARM toolchain requires the file `/lib/ld-linux.so.3` to exist. The installer creates a symbolic link to `/lib/ld-linux-armhf.so.3` if needed. If PlatformIO reports a "No such file or directory" error for the linker, apply the fix manually:

```bash
sudo ln -s /lib/ld-linux-armhf.so.3 /lib/ld-linux.so.3
```

---

## The Dashboard Shows Stale Data After Reboot

**Symptom:** After rebooting the Pi, the dashboard shows old readings from before the reboot.

This is expected behavior. The database persists across reboots. The ESP32 status indicator will show **Offline** until a fresh telemetry update arrives (within a few seconds of the ESP32 reconnecting to Wi-Fi after the Pi comes back up). Once the ESP32 posts a new update, the live readings will refresh.

---

## Password Reset

If you have forgotten your DryDock password, you can reset it directly in the database using the Flask shell.

```bash
cd ~/DryDock
source .venv/bin/activate
export FLASK_APP=app.py
flask shell
```

Inside the Flask shell:

```python
from drydock.extensions import db
from drydock.models import User
from werkzeug.security import generate_password_hash

user = User.query.first()
user.password_hash = generate_password_hash("your_new_password")
db.session.commit()
exit()
```

---

## Viewing Application Logs

For detailed diagnostic information, check the structured event log:

```bash
cat ~/DryDock/instance/logs/drydock.jsonl | tail -50
```

Or follow the systemd journal in real time:

```bash
sudo journalctl -u drydock -f
```

Set **Log Level** to `DEBUG` in the Settings page to capture all incoming telemetry in the structured log. Remember to switch back to `INFO` once the issue is diagnosed.
