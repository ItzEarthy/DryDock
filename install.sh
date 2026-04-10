#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# --- FLAG PARSING ---
SKIP_WIFI=false
FIX_ENV=false

while getopts "sf" opt; do
  case $opt in
    s) SKIP_WIFI=true ;;
    f) FIX_ENV=true ;;
    *) echo "Usage: ./install.sh [-s (skip wifi)] [-f (only add missing .env parts)]"; exit 1 ;;
  esac
done

echo "Starting DryDock Installation..."

APP_DIR="$(pwd)"
APP_USER="$(whoami)"
ENV_FILE=".env"

# Ensure .env exists
touch "$ENV_FILE"

# Helper function to prompt only if needed
prompt_if_missing() {
    local key=$1
    local prompt_msg=$2
    local secret=$3

    # If -f (fix-env) is enabled, skip if the key already exists and isn't empty
    if [ "$FIX_ENV" = true ] && grep -q "^$key=" "$ENV_FILE" && [ -n "$(grep "^$key=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '\"')" ]; then
        return
    fi

    if [ "$secret" = "true" ]; then
        read -s -p "$prompt_msg: " val
        echo ""
    else
        read -p "$prompt_msg: " val
    fi

    # Update or append to .env
    if grep -q "^$key=" "$ENV_FILE"; then
        sed -i "s|^$key=.*|$key=\"$val\"|" "$ENV_FILE"
    else
        echo "$key=\"$val\"" >> "$ENV_FILE"
    fi
}

# --- 1. INTERACTIVE SETUP ---
echo ""
echo "--- Configuration ---"

if [ "$SKIP_WIFI" = false ]; then
    prompt_if_missing "WIFI_SSID" "Enter WiFi SSID" "false"
    prompt_if_missing "WIFI_PASS" "Enter WiFi Password" "true"
fi

prompt_if_missing "BOARD_ID" "Enter Board ID (esp32dev, esp32-s3-devkitc-1, esp32-c3-devkitc-02)" "false"

# Update PI_IP automatically every time
PI_IP=$(hostname -I | awk '{print $1}')
if grep -q "^PI_IP=" "$ENV_FILE"; then
    sed -i "s|^PI_IP=.*|PI_IP=\"$PI_IP\"|" "$ENV_FILE"
else
    echo "PI_IP=\"$PI_IP\"" >> "$ENV_FILE"
fi

# Moonraker update manager prompt (only if -f is not set or it's missing)
if ! grep -q "update_manager drydock" ~/printer_data/config/moonraker.conf 2>/dev/null; then
    read -p "Add DryDock to Moonraker Update Manager? (y/N): " ADD_MOONRAKER
    if [[ "$ADD_MOONRAKER" =~ ^[Yy]$ ]]; then
        MOONRAKER_CONF="$HOME/printer_data/config/moonraker.conf"
        if [ -f "$MOONRAKER_CONF" ]; then
            cat <<EOF >> "$MOONRAKER_CONF"

[update_manager drydock]
type: git_repo
path: $APP_DIR
origin: https://github.com/ItzEarthy/DryDock.git
primary_branch: main
is_system_service: False
EOF
        fi
    fi
fi

# --- 2. SYSTEM DEPENDENCIES & COMPILER FIX ---
echo "Installing system dependencies..."
sudo apt update
sudo apt install -y python3-venv python3-pip curl git build-essential

# Raspberry Pi toolchain linker fix for Trixie/32-bit architecture
if [ -f "/lib/ld-linux-armhf.so.3" ] && [ ! -f "/lib/ld-linux.so.3" ]; then
    echo "Applying Raspberry Pi toolchain linker fix..."
    sudo ln -s /lib/ld-linux-armhf.so.3 /lib/ld-linux.so.3
fi

# --- 3. USB PERMISSIONS ---
echo "Setting up USB permissions..."
curl -fsSL https://raw.githubusercontent.com/platformio/platformio-core/develop/scripts/99-platformio-udev.rules | sudo tee /etc/udev/rules.d/99-platformio-udev.rules > /dev/null
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -a -G dialout "$APP_USER"

# --- 4. PYTHON ENVIRONMENT ---
echo "Setting up Python Virtual Environment..."
[ ! -d ".venv" ] && python3 -m venv .venv
source .venv/bin/activate
pip install Flask Flask-SQLAlchemy Werkzeug APScheduler Flask-Migrate requests platformio

# --- 5. DATABASE ---
echo "Initializing the database..."
export FLASK_APP=app.py
flask db init || true
flask db migrate -m "Initial install" || true
flask db upgrade || true

# --- 6. SYSTEMD SERVICE ---
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

sudo systemctl daemon-reload
sudo systemctl enable drydock.service
sudo systemctl restart drydock.service

echo "====================================================="
echo " Installation Complete! "
echo " Dashboard: http://$PI_IP:5000"
echo " Usage: ./install.sh -s (skip wifi) or -f (fix/add missing)"
echo "====================================================="