#!/bin/bash
# ==============================================================================
# Easibot Auto-Start & Auto-Update Service Installer
# Automatically configures systemd for your current Raspberry Pi username & path!
# Usage:
#   ./scripts/install_autostart.sh           (runs main.py)
#   ./scripts/install_autostart.sh demo.py   (runs demo.py)
# ==============================================================================

set -e

cd "$(dirname "$0")/.."
REPO_DIR="$(pwd)"
CURRENT_USER="$(whoami)"
USER_UID="$(id -u)"
ENTRY_SCRIPT="${1:-main.py}"

chmod +x scripts/*.sh

echo "======================================================================"
echo " Installing Easibot Auto-Start + Auto-Update Service"
echo "   User      : $CURRENT_USER (UID=$USER_UID)"
echo "   Directory : $REPO_DIR"
echo "   Script    : $ENTRY_SCRIPT"
echo "======================================================================"

# Keep PipeWire/PulseAudio user session alive even before SSH login
sudo loginctl enable-linger "$CURRENT_USER" || true

# Generate tailored systemd unit file
SERVICE_TMP="/tmp/easibot.service"
cat << EOF > "$SERVICE_TMP"
[Unit]
Description=Easibot AI Multilingual Assistant Robot
After=network-online.target sound.target bluetooth.target
Wants=network-online.target bluetooth.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$REPO_DIR
ExecStart=$REPO_DIR/scripts/run_service.sh $ENTRY_SCRIPT
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1
Environment=XDG_RUNTIME_DIR=/run/user/$USER_UID

[Install]
WantedBy=multi-user.target
EOF

sudo mv "$SERVICE_TMP" /etc/systemd/system/easibot.service
sudo systemctl daemon-reload
sudo systemctl enable easibot.service
sudo systemctl restart easibot.service

echo ""
echo "✓ Easibot Auto-Start & Auto-Update Service installed and started!"
echo "  Check status : sudo systemctl status easibot"
echo "  Live logs    : journalctl -u easibot -f"
echo "  Stop service : sudo systemctl stop easibot"
echo "======================================================================"
