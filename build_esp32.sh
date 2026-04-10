#!/bin/bash
set -e

echo "Building ESP32 Firmware..."
source .venv/bin/activate

# 1. Setup PlatformIO folder
mkdir -p firmware
cd firmware
if [ ! -f "platformio.ini" ]; then
    pio project init --board esp32dev --project-option "framework=arduino"
    pio pkg install --library "miguelbalboa/MFRC522" --library "adafruit/Adafruit AM2320 sensor library" --library "adafruit/Adafruit NAU7802 Library"
fi
cd ..

# 2. Generate the C++ code using your Python script
echo "Injecting WiFi and Server data into main.cpp..."
source .env
export WIFI_SSID
export WIFI_PASS
export PI_IP

# Make sure Python can find the drydock module
export PYTHONPATH="$(pwd)"

python3 -c "
import os
from drydock.utils.firmware import generate_esp32_firmware

ssid = os.environ.get('WIFI_SSID', '')
pwd = os.environ.get('WIFI_PASS', '')
# Make sure this matches your Flask route
server_url = f'http://{os.environ.get(\"PI_IP\")}:5000/api/telemetry' 

cpp_code = generate_esp32_firmware(ssid, pwd, server_url)

with open('firmware/src/main.cpp', 'w') as f:
    f.write(cpp_code)
"

# 3. Compile
cd firmware
echo "Compiling..."
pio run

echo "==========================="
echo " Build complete!"
echo "==========================="