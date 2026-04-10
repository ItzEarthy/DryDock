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

echo "====================================================="
echo "          DryDock Installation Wizard                "
echo "====================================================="

APP_DIR="$(pwd)"
APP_USER="$(whoami)"
ENV_FILE=".env"

touch "$ENV_FILE"

# Helper for standard text/password prompts
prompt_user() {
    local key=$1
    local label=$2
    local secret=$3
    local current_val=$(grep "^$key=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '\"' || true)

    if [ "$FIX_ENV" = true ] && [ -n "$current_val" ]; then return; fi

    echo -n "  > $label"
    [ -n "$current_val" ] && echo -n " [$current_val]"
    echo -n ": "

    if [ "$secret" = "true" ]; then
        read -s val
        echo ""
    else
        read val
    fi

    val=${val:-$current_val}
    if grep -q "^$key=" "$ENV_FILE"; then
        sed -i "s|^$key=.*|$key=\"$val\"|" "$ENV_FILE"
    else
        echo "$key=\"$val\"" >> "$ENV_FILE"
    fi
}

# --- 1. CONFIGURATION ---
echo ""
echo "--- Firmware Settings ---"

if [ "$SKIP_WIFI" = false ]; then
    prompt_user "WIFI_SSID" "WiFi Network Name" "false"
    prompt_user "WIFI_PASS" "WiFi Password" "true"
fi

# Numeric Board Selection
if [ "$FIX_ENV" = false ] || ! grep -q "^BOARD_ID=" "$ENV_FILE"; then
    echo "  > Select Board Type:"
    echo "    1) Standard ESP32 (esp32dev)"
    echo "    2) ESP32-S3 (esp32-s3-devkitc-1)"
    echo "    3) ESP32-C3 (esp32-c3-devkitc-02)"
    echo -n "  Enter choice [1-3]: "
    read BOARD_CHOICE
    case $BOARD_CHOICE in
        2) B_ID="esp32-s3-devkitc-1" ;;
        3) B_ID="esp32-c3-devkitc-02" ;;
        *) B_ID="esp32dev" ;;
    esac
    if grep -q "^BOARD_ID=" "$ENV_FILE"; then
        sed -i "s|^BOARD_ID=.*|BOARD_ID=\"$B_ID\"|" "$ENV_FILE"
    else
        echo "BOARD_ID=\"$B_ID\"" >> "$ENV_FILE"
    fi
fi

# Auto-update PI_IP
PI_IP=$(hostname -I | awk '{print $1}')
sed -i "/^PI_IP=/d" "$ENV_FILE" && echo "PI_IP=\"$PI_IP\"" >> "$ENV_FILE"

echo ""
echo "--- Klipper Integration ---"
if ! grep -q "update_manager drydock" ~/printer_data/config/moonraker.conf 2>/dev/null; then
    echo "  > Add to Moonraker Update Manager?"
    echo "    1) Yes"
    echo "    2) No"
    echo -n "  Enter choice [1-2]: "
    read MOON_CHOICE
    if [ "$MOON_CHOICE" = "1" ]; then
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
            echo "  [OK] Added to Moonraker."
        fi
    fi
fi

# --- 2. SYSTEM DEPENDENCIES & FIXES ---
echo ""
echo "--- Installing Dependencies ---"
sudo apt update && sudo apt install -y python3-venv python3-pip curl git build-essential

# Pi Linker Fix
if [ -f "/lib/ld-linux-armhf.so.3" ] && [ ! -f "/lib/ld-linux.so.3" ]; then
    echo "  Applying Pi toolchain fix..."
    sudo ln -s /lib/ld-linux-armhf.so.3 /lib/ld-linux.so.3
fi

# --- 3. USB PERMISSIONS ---
echo "--- Configuring USB Permissions ---"
curl -fsSL https://raw.githubusercontent.com/platformio/platformio-core/develop/scripts/99-platformio-udev.rules | sudo tee /etc/udev/rules.d/99-platformio-udev.rules > /dev/null
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -a -G dialout "$APP_USER"

# --- 4. PYTHON ENVIRONMENT ---
echo "--- Setting up Environment ---"
[ ! -d ".venv" ] && python3 -m venv .venv
source .venv/bin/activate
pip install Flask Flask-SQLAlchemy Werkzeug APScheduler Flask-Migrate requests platformio

# --- 5. DATABASE ---
echo "--- Initializing Database ---"
export FLASK_APP=app.py
flask db init || true
flask db migrate -m "Initial install" || true
flask db upgrade || true

# --- 6. SERVICE ---
echo "--- Installing Background Service ---"
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

sudo systemctl daemon-reload && sudo systemctl enable drydock.service && sudo systemctl restart drydock.service

echo ""
echo "====================================================="
echo "             Installation Complete!                  "
echo " Dashboard: http://$PI_IP:5000"
echo "====================================================="