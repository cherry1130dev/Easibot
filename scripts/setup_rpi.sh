#!/bin/bash
# ==============================================================================
# Easibot: Raspberry Pi Zero 2 W Hardware & Environment Setup Script
# Compatible with Raspberry Pi OS Bookworm / Trixie (64-bit and 32-bit)
# ==============================================================================

set -e

echo "======================================================================"
echo " Starting Easibot Setup for Raspberry Pi Zero 2 W"
echo "======================================================================"

# 1. Update APT repository
echo "[1/7] Updating package index..."
sudo apt-get update -y

# 2. Install essential system dependencies, fonts, and audio packages
echo "[2/7] Installing Indic fonts, audio tools, and system libraries..."
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    python3-dev \
    python3-spidev \
    python3-rpi.gpio \
    python3-gpiozero \
    fonts-noto-core \
    fonts-noto-telugu \
    fonts-noto-deva \
    fonts-dejavu-core \
    libraqm0 \
    libraqm-dev \
    libfreetype6-dev \
    libjpeg-dev \
    zlib1g-dev \
    mpg123 \
    alsa-utils \
    portaudio19-dev \
    libasound2-dev \
    pipewire \
    pipewire-audio-client-libraries \
    wireplumber \
    bluez \
    bluez-tools

# 3. Enable SPI & I2C Hardware Interfaces
echo "[3/7] Enabling SPI and I2C hardware interfaces..."
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0

# 4. Raspberry Pi Zero 2 W Memory Optimization (ZRAM for 512MB RAM)
echo "[4/7] Configuring ZRAM swap for 512MB RAM optimization..."
if ! command -v zramctl &> /dev/null; then
    sudo apt-get install -y zram-tools
    echo "PERCENT=60" | sudo tee -a /etc/default/zramswap
    echo "ALGO=lz4" | sudo tee -a /etc/default/zramswap
    sudo systemctl restart zramswap || true
fi

# 5. Create Python Virtual Environment with system site packages
echo "[5/7] Setting up Python virtual environment..."
cd "$(dirname "$0")/.."
if [ ! -d "venv" ]; then
    python3 -m venv --system-site-packages venv
fi

source venv/bin/activate
pip install --upgrade pip

# 6. Install Python Requirements & Adafruit Hardware Libraries
echo "[6/7] Installing Python dependencies..."
pip install -r requirements.txt
pip install adafruit-circuitpython-rgb-display RPi.GPIO gpiozero spidev

# 7. Copy Font Files locally if needed
mkdir -p assets/fonts
cp -u /usr/share/fonts/truetype/noto/NotoSans-Regular.ttf assets/fonts/ 2>/dev/null || true
cp -u /usr/share/fonts/truetype/noto/NotoSansTelugu-Regular.ttf assets/fonts/ 2>/dev/null || true
cp -u /usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf assets/fonts/ 2>/dev/null || true

echo "======================================================================"
echo " Easibot setup completed successfully!"
echo " Next Steps:"
echo " 1. Configure .env file with your GEMINI_API_KEY:"
echo "    cp .env.example .env && nano .env"
echo " 2. Connect Bluetooth Speaker via:"
echo "    ./scripts/setup_bluetooth.sh"
echo " 3. Launch Easibot:"
echo "    source venv/bin/activate && python main.py"
echo "======================================================================"
