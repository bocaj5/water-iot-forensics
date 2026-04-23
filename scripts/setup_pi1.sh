#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# setup_pi1.sh  –  One-shot bootstrap for Sensor Gateway (Raspberry Pi 2B)
# Run as root:  sudo bash setup_pi1.sh
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

HOSTNAME="water-pi1"
PROJECT_DIR="/opt/water-monitor"
VENV_DIR="$PROJECT_DIR/venv"
SERVICE_NAME="water-sensor-gateway"
USER_NAME="pi"

echo "======================================"
echo " Sensor Gateway (Pi 1) Setup"
echo "======================================"

# ── 1. System update & hostname ──────────────────────────────────────
echo "[1/7] Updating system and setting hostname..."
apt-get update -qq && apt-get upgrade -y -qq
hostnamectl set-hostname "$HOSTNAME"
grep -q "$HOSTNAME" /etc/hosts || sed -i "s/127.0.1.1.*/127.0.1.1\t$HOSTNAME/" /etc/hosts

# ── 2. Install system dependencies ──────────────────────────────────
echo "[2/7] Installing system packages..."
apt-get install -y -qq \
    python3 python3-pip python3-venv python3-dev \
    avahi-daemon avahi-utils \
    git libffi-dev libssl-dev \
    i2c-tools

# Enable avahi for mDNS (.local resolution)
systemctl enable avahi-daemon
systemctl start avahi-daemon

# ── 3. Enable GPIO / I2C interfaces ─────────────────────────────────
echo "[3/7] Enabling hardware interfaces..."
raspi-config nonint do_i2c 0 2>/dev/null || true
raspi-config nonint do_spi 0 2>/dev/null || true

# ── 4. Copy project files ───────────────────────────────────────────
echo "[4/7] Setting up project directory..."
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$PROJECT_DIR"
rsync -a --exclude='venv' --exclude='__pycache__' --exclude='.git' \
    --exclude='old' --exclude='tests/test data' \
    "$SCRIPT_DIR/" "$PROJECT_DIR/"
chown -R "$USER_NAME:$USER_NAME" "$PROJECT_DIR"

# ── 5. Python virtual environment & dependencies ────────────────────
echo "[5/7] Creating Python venv and installing dependencies..."
sudo -u "$USER_NAME" python3 -m venv "$VENV_DIR"
sudo -u "$USER_NAME" "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel
sudo -u "$USER_NAME" "$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements_pi1.txt"

# ── 6. Generate crypto keys (shared keypair with Pi 2) ──────────────
echo "[6/7] Generating RSA keys (if not present)..."
KEY_DIR="$PROJECT_DIR/crypto_keys"
mkdir -p "$KEY_DIR"
if [ ! -f "$KEY_DIR/forensic_private.pem" ]; then
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 \
        -out "$KEY_DIR/forensic_private.pem" 2>/dev/null
    openssl rsa -in "$KEY_DIR/forensic_private.pem" \
        -pubout -out "$KEY_DIR/forensic_public.pem" 2>/dev/null
    chmod 600 "$KEY_DIR/forensic_private.pem"
    chmod 644 "$KEY_DIR/forensic_public.pem"
    chown -R "$USER_NAME:$USER_NAME" "$KEY_DIR"
    echo "  → RSA-4096 keypair generated."
    echo "  → IMPORTANT: Copy forensic_public.pem to Pi 2 (or use the same keypair)."
else
    echo "  → Keys already exist, skipping."
fi

# ── 7. Install systemd service ──────────────────────────────────────
echo "[7/7] Installing systemd service..."
cp "$PROJECT_DIR/scripts/$SERVICE_NAME.service" "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo ""
echo "======================================"
echo " Setup complete!"
echo "======================================"
echo ""
echo " Hostname : $HOSTNAME (reboot to apply)"
echo " Project  : $PROJECT_DIR"
echo " Venv     : $VENV_DIR"
echo " Service  : $SERVICE_NAME"
echo ""
echo " To start now:  sudo systemctl start $SERVICE_NAME"
echo " To run interactive: cd $PROJECT_DIR && $VENV_DIR/bin/python main_node1.py --mode interactive"
echo ""
echo " NOTE: Copy the same crypto_keys/ folder to Pi 2 for shared encryption."
echo ""
