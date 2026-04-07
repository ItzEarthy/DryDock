#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "Starting DryDock Installation..."

# Get current user and absolute directory path
APP_DIR="$(pwd)"
APP_USER="$(whoami)"

echo "Installing system dependencies..."
sudo apt update
sudo apt install -y python3-venv python3-pip

echo "Setting up Python Virtual Environment..."
python3 -m venv .venv
source .venv/bin/activate

echo "Installing Python packages..."
pip install Flask Flask-SQLAlchemy Werkzeug APScheduler Flask-Migrate

echo "Initializing the database..."
export FLASK_APP=app.py
# Initialize migrations (ignores errors if already initialized)
flask db init || true
flask db migrate -m "Initial install" || true
flask db upgrade || true

echo "Creating systemd background service..."
# Dynamically create the service file with the correct paths and user
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

# Get the Pi's local IP address
PI_IP=$(hostname -I | awk '{print $1}')

echo "====================================================="
echo " Installation Complete! "
echo " DryDock is now running in the background."
echo " Access the dashboard at: http://$PI_IP:5000"
echo "====================================================="