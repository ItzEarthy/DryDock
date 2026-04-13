#!/bin/bash
set -e
source .venv/bin/activate

echo "--- Searching for ESP32 ---"
PORTS=($(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true))

if [ ${#PORTS[@]} -eq 0 ]; then
    echo "Error: No devices found."; exit 1
elif [ ${#PORTS[@]} -eq 1 ]; then
    UPLOAD_PORT=${PORTS[0]}
else
    echo "Multiple devices found. Select port number:"
    select UPLOAD_PORT in "${PORTS[@]}"; do
        [ -n "$UPLOAD_PORT" ] && break || echo "Invalid selection."
    done
fi

cd firmware

echo "--- Erasing Flash ---"
pio run --target erase --upload-port "$UPLOAD_PORT"

echo "--- Uploading Firmware ---"
pio run --target upload --upload-port "$UPLOAD_PORT"

echo "--- Flash Complete ---"
echo "--- Monitoring Logs for 10 Seconds ---"

# The '|| true' prevents the script from throwing an error when the timeout kills the monitor
timeout 10s pio device monitor --port "$UPLOAD_PORT" --baud 115200 || true

echo "--- Done ---"
