# Firmware Setup

DryDock provides a built-in firmware generator that produces a ready-to-compile `.ino` file pre-configured with your Wi-Fi credentials and server address. This page explains how to generate the firmware file and flash it to your ESP32.

## Required Arduino Libraries

Before you can compile the firmware, install the following libraries in the Arduino IDE or PlatformIO. All are available in the standard library managers.

| Library | Author | Purpose |
|---|---|---|
| `MFRC522` | miguelbalboa | RFID reader driver |
| `Adafruit AM2320` | Adafruit | Temperature and humidity sensor driver |
| `Adafruit NAU7802` | Adafruit | 24-bit ADC / load cell driver |
| `WiFi` | Espressif (built-in) | Wi-Fi connectivity for ESP32 |
| `HTTPClient` | Espressif (built-in) | HTTP POST to the Flask backend |

In the **Arduino IDE**, open the Library Manager (**Sketch > Include Library > Manage Libraries**), search for each library name, and click **Install**.

## Step 1 - Generate the Firmware File

1. Open the DryDock dashboard in a browser.
2. Log in if prompted.
3. Navigate to the **Settings** page (accessible from the navigation menu).
4. Scroll to the **Firmware** section.
5. Fill in the following fields:
   - **Wi-Fi SSID:** The name of the Wi-Fi network your ESP32 should connect to.
   - **Wi-Fi Password:** The password for that network.
   - **Server IP:** The IP address of the Raspberry Pi running DryDock. The dashboard pre-fills this field with the detected host IP.
   - **Server Port:** The port the Flask backend listens on. The default is `5000`.
6. Click **Generate Firmware**. The browser will download a file named `DryDock.ino`.

The downloaded file is complete C++ source code for the Arduino IDE. It includes your credentials injected directly into the appropriate string constants. Keep this file private if you are sharing your project publicly, as it contains your Wi-Fi password in plain text.

## Step 2 - Open the Project in Arduino IDE

1. Open the **Arduino IDE**.
2. Go to **File > Open** and select the `DryDock.ino` file you downloaded.
3. The IDE will offer to create a new project folder (sketch directory). Click **OK**.

## Step 3 - Select the Board and Port

1. In the Arduino IDE, go to **Tools > Board > ESP32 Arduino** and select the board that matches your hardware:
   - For ESP32-S3: select **ESP32S3 Dev Module**.
   - For standard ESP32: select **ESP32 Dev Module**.
2. Connect your ESP32 to your computer via USB.
3. Go to **Tools > Port** and select the COM port or `/dev/ttyUSB*` port that corresponds to your ESP32. If you do not see the device listed, make sure the USB driver for your ESP32's USB-to-serial chip (CP2102 or CH340) is installed.

## Step 4 - Compile and Upload

1. Click the **Upload** button (the right-pointing arrow at the top of the IDE), or go to **Sketch > Upload**.
2. The IDE will compile the sketch and upload it to the ESP32. This may take a minute or two.
3. When the upload is complete, the IDE will print `Done uploading.` in the output panel.
4. The ESP32 will reboot and immediately begin connecting to Wi-Fi and posting telemetry to the DryDock backend.

## Step 5 - Verify the Connection

1. Open the **Arduino Serial Monitor** (**Tools > Serial Monitor**) and set the baud rate to **115200**.
2. You should see the ESP32 boot messages. If sensors are detected, they will be initialized silently.
3. Switch to the DryDock dashboard. Within a few seconds, the **ESP32 Status** indicator should change to **Online** and live sensor readings should appear.

If the ESP32 does not appear online within 30 seconds, check the [Troubleshooting](Troubleshooting) page.

## Firmware Behavior

Once flashed, the firmware operates as follows:

- **Telemetry heartbeat:** The ESP32 posts sensor data to the backend every 5 seconds during normal operation.
- **RFID scan:** When a new NFC tag is presented to the MFRC522 reader, a telemetry update is sent immediately, bypassing the 5-second interval.
- **Weight event:** If the measured weight changes by more than 200 grams (indicating a spool was placed on or removed from the scale), an update is sent at most once per second until the reading stabilizes.
- **Weight stability (hardening):** The firmware uses an Exponential Moving Average (EMA) filter to smooth the raw ADC readings. The weight is considered stable after the EMA reading has not changed by more than 3 grams for 4 consecutive seconds. The dashboard shows a progress bar reflecting this hardening state.

## Serial Commands

You can send commands to the ESP32 through the Arduino Serial Monitor for basic diagnostics. All commands are plain text, followed by pressing Enter.

| Command | Response |
|---|---|
| `TARE` | Immediately re-tares the scale to the current reading. Responds with `{"status":"tared"}` |
| `WEIGHT` | Reports the current stable weight in grams. Responds with `{"weight":<value>}` |
| `ENV` | Reports the temperature and humidity from AM2320 #1 (inside sensor). Responds with `{"temp":<value>,"hum":<value>}` |

## Flashing Without the Arduino IDE

If you prefer to use the command line, the `flash_esp32.sh` and `build_esp32.sh` scripts in the project root use **PlatformIO** to compile and flash the firmware. PlatformIO is installed as part of the Python virtual environment during the `install.sh` process.

```bash
cd ~/DryDock
source .venv/bin/activate
bash build_esp32.sh   # Compile only
bash flash_esp32.sh   # Compile and flash
```

Note that these scripts use the firmware template stored in the project and inject credentials from the `.env` file. They are an alternative to the web-based generator and are primarily intended for command-line or CI use.
