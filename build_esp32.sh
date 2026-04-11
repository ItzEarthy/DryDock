#!/bin/bash
set -e

[ ! -f .env ] && { echo "Error: .env not found. Run ./install.sh"; exit 1; }
source .env
BOARD_ID=${BOARD_ID:-esp32dev}

echo "--- Building Firmware for: $BOARD_ID ---"
source .venv/bin/activate

mkdir -p firmware
cd firmware
if [ -f "platformio.ini" ] && ! grep -q "board = $BOARD_ID" platformio.ini; then
    rm -rf .pio platformio.ini
fi

if [ ! -f "platformio.ini" ]; then
    echo "Initializing PlatformIO with S3 Compatibility Fixes..."
    pio project init --board "$BOARD_ID" \
        --project-option "framework=arduino" \
        --project-option "board_build.flash_mode = dio" \
        --project-option "board_build.arduino.memory_type = qio_qspi"
    
    # Re-install libraries
    pio pkg install --library "miguelbalboa/MFRC522" \
                    --library "adafruit/Adafruit AM2320 sensor library" \
                    --library "adafruit/Adafruit NAU7802 Library"
fi
cd ..

export PYTHONPATH="$(pwd)"
export WIFI_SSID WIFI_PASS PI_IP

python3 -c "
import os
from drydock.utils.firmware import generate_esp32_firmware
ssid = os.environ.get('WIFI_SSID', '')
pwd = os.environ.get('WIFI_PASS', '')
url = f'http://{os.environ.get("PI_IP")}:5000/api/update'
with open('firmware/src/main.cpp', 'w') as f:
    f.write(generate_esp32_firmware(ssid, pwd, url))
"

cd firmware && pio run
echo "--- Build Complete ---"