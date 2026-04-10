#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "Starting DryDock Installation..."

APP_DIR="$(pwd)"
APP_USER="$(whoami)"

# --- INTERACTIVE SETUP ---
echo ""
echo "--- ESP32 Firmware Configuration ---"
read -p "Enter the WiFi SSID for DryDock: " WIFI_SSID
read -s -p "Enter the WiFi Password: " WIFI_PASS
echo ""

echo "WIFI_SSID=\"$WIFI_SSID\"" > .env
echo "WIFI_PASS=\"$WIFI_PASS\"" >> .env
echo "Variables saved to .env."

echo "Installing system dependencies..."
sudo apt update
sudo apt install -y python3-venv python3-pip curl git

echo "Setting up USB permissions for flashing the ESP32..."
curl -fsSL https://raw.githubusercontent.com/platformio/platformio-core/develop/scripts/99-platformio-udev.rules | sudo tee /etc/udev/rules.d/99-platformio-udev.rules > /dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -a -G dialout $APP_USER

echo "Setting up Python Virtual Environment..."
python3 -m venv .venv
source .venv/bin/activate

echo "Installing Python packages..."
pip install Flask Flask-SQLAlchemy Werkzeug APScheduler Flask-Migrate requests platformio

echo "Initializing the database..."
export FLASK_APP=app.py
flask db init || true
flask db migrate -m "Initial install" || true
flask db upgrade || true

echo "Creating systemd background service..."
cat <<EOF | sudo tee /etc/systemd/system/drydock.service > /dev/null
[Unit]
Description=DryDock Flask Application
After=network.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "Enabling and starting DryDock service..."
sudo systemctl daemon-reload
sudo systemctl enable drydock.service
sudo systemctl restart drydock.service

# Get the Pi's local IP address and append to .env
PI_IP=$(hostname -I | awk '{print $1}')
echo "PI_IP=\"$PI_IP\"" >> .env

echo "====================================================="
echo " Installation Complete! "
echo " DryDock dashboard: http://$PI_IP:5000"
echo " Note: You may need to log out and back in for USB permissions to take effect."
echo "====================================================="