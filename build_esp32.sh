#!/bin/bash
set -e

# Load environment variables (WIFI, IP, and Board Type)
if [ -f .env ]; then
    source .env
else
    echo "Error: .env file not found. Please run ./install.sh first."
    exit 1
fi

# Use esp32dev as a default if no board was selected in install.sh
BOARD_ID=${BOARD_ID:-esp32dev}

echo "Building DryDock Firmware for board: $BOARD_ID..."

# Activate the virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "Error: Virtual environment (.venv) not found. Please run ./install.sh."
    exit 1
fi

# 1. Setup PlatformIO folder and project
mkdir -p firmware
cd firmware

# If platformio.ini exists but is for a different board, clear it to re-initialize
if [ -f "platformio.ini" ] && ! grep -q "board = $BOARD_ID" platformio.ini; then
    echo "Board change detected. Updating project configuration for $BOARD_ID..."
    rm -rf .pio platformio.ini
fi

# Initialize the project if needed
if [ ! -f "platformio.ini" ]; then
    echo "Initializing PlatformIO project..."
    pio project init --board "$BOARD_ID" --project-option "framework=arduino"
    
    # Install required libraries
    echo "Installing hardware libraries..."
    pio pkg install --library "miguelbalboa/MFRC522" 
    pio pkg install --library "adafruit/Adafruit AM2320 sensor library" 
    pio pkg install --library "adafruit/Adafruit NAU7802 Library"
fi
cd ..

# 2. Generate the C++ code using the Python utility
echo "Injecting WiFi and Server data into main.cpp..."

# Ensure Python can find the drydock module in the current directory
export PYTHONPATH="$(pwd)"
export WIFI_SSID
export WIFI_PASS
export PI_IP

python3 -c "
import os
from drydock.utils.firmware import generate_esp32_firmware

ssid = os.environ.get('WIFI_SSID', '')
pwd = os.environ.get('WIFI_PASS', '')
# Ensure the telemetry URL points to this Pi
server_url = f'http://{os.environ.get(\"PI_IP\")}:5000/api/telemetry' 

cpp_code = generate_esp32_firmware(ssid, pwd, server_url)

with open('firmware/src/main.cpp', 'w') as f:
    f.write(cpp_code)
"

# 3. Compile the binary
cd firmware
echo "Starting compilation..."
pio run

echo "==========================="
echo " Build successful!"
echo " You can now run ./flash_esp32.sh"
echo "==========================="