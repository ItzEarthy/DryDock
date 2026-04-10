#!/bin/bash
set -e

echo "Flashing ESP32 Firmware..."
source .venv/bin/activate

echo "Scanning for connected USB devices..."

# Find all standard USB serial ports on a Pi
PORTS=($(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true))

if [ ${#PORTS[@]} -eq 0 ]; then
    echo "Error: No serial devices found."
    echo "Please plug in the ESP32 and run this script again."
    exit 1
elif [ ${#PORTS[@]} -eq 1 ]; then
    # Auto-select if only one device is found
    UPLOAD_PORT=${PORTS[0]}
    echo "Found only one device: $UPLOAD_PORT"
else
    # Provide a menu if multiple devices are found
    echo "Multiple devices found. Which port is your DryDock ESP32 connected to?"
    echo "(Tip: If you aren't sure, unplug it, run 'ls /dev/ttyUSB*', plug it back in, and see what gets added)"
    
    select UPLOAD_PORT in "${PORTS[@]}"; do
        if [ -n "$UPLOAD_PORT" ]; then
            echo "You selected: $UPLOAD_PORT"
            break
        else
            echo "Invalid selection. Please enter a number."
        fi
    done
fi

cd firmware

echo "Uploading to ESP32 on $UPLOAD_PORT..."
# Pass the specific port to PlatformIO
pio run --target upload --upload-port "$UPLOAD_PORT"

echo "==========================="
echo " Flashing complete!"
echo "==========================="