#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# setup_pi2.sh  –  One-shot bootstrap for Forensic Guardian (Raspberry Pi 4B)
# Run as root:  sudo bash setup_pi2.sh
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

HOSTNAME="water-pi2"
PROJECT_DIR="/opt/water-monitor"
VENV_DIR="$PROJECT_DIR/venv"
SERVICE_NAME="water-forensic-guardian"
USER_NAME="pi"
USB_MOUNT="/mnt/encrypted_usb"

echo "======================================"
echo " Forensic Guardian (Pi 2) Setup"
echo "======================================"

# ── 1. System update & hostname ──────────────────────────────────────
echo "[1/9] Updating system and setting hostname..."
apt-get update -qq && apt-get upgrade -y -qq
hostnamectl set-hostname "$HOSTNAME"
grep -q "$HOSTNAME" /etc/hosts || sed -i "s/127.0.1.1.*/127.0.1.1\t$HOSTNAME/" /etc/hosts

# ── 2. Install system dependencies ──────────────────────────────────
echo "[2/9] Installing system packages..."
apt-get install -y -qq \
    python3 python3-pip python3-venv python3-dev \
    avahi-daemon avahi-utils \
    git libffi-dev libssl-dev \
    cryptsetup \
    libatlas-base-dev libhdf5-dev

# Enable avahi for mDNS (.local resolution)
systemctl enable avahi-daemon
systemctl start avahi-daemon

# ── 3. LUKS encrypted USB setup ─────────────────────────────────────
echo "[3/9] Preparing LUKS USB mount point..."
mkdir -p "$USB_MOUNT"
mkdir -p "$USB_MOUNT/evidence"

echo ""
echo "  LUKS USB SETUP INSTRUCTIONS:"
echo "  ─────────────────────────────"
echo "  1. Insert the USB drive"
echo "  2. Find the device: lsblk"
echo "  3. Format with LUKS: sudo cryptsetup luksFormat /dev/sdX"
echo "  4. Open: sudo cryptsetup luksOpen /dev/sdX evidence_usb"
echo "  5. Create FS: sudo mkfs.ext4 /dev/mapper/evidence_usb"
echo "  6. Mount: sudo mount /dev/mapper/evidence_usb $USB_MOUNT"
echo ""
echo "  Or run: sudo bash $PROJECT_DIR/scripts/setup_luks.sh /dev/sdX"
echo ""

# ── 4. Copy project files ───────────────────────────────────────────
echo "[4/9] Setting up project directory..."
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

mkdir -p "$PROJECT_DIR"
rsync -a --exclude='venv' --exclude='__pycache__' --exclude='.git' \
    --exclude='old' \
    "$SCRIPT_DIR/" "$PROJECT_DIR/"
chown -R "$USER_NAME:$USER_NAME" "$PROJECT_DIR"

# ── 5. Python virtual environment & dependencies ────────────────────
echo "[5/9] Creating Python venv and installing dependencies..."
sudo -u "$USER_NAME" python3 -m venv "$VENV_DIR"
sudo -u "$USER_NAME" "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel

# Install TFLite runtime (ARM-specific)
echo "  → Installing TensorFlow Lite runtime for ARM..."
sudo -u "$USER_NAME" "$VENV_DIR/bin/pip" install \
    tflite-runtime 2>/dev/null || \
    echo "  → tflite-runtime not available for this platform, will use tensorflow"

sudo -u "$USER_NAME" "$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements_pi2.txt"

# ── 6. Generate crypto keys ─────────────────────────────────────────
echo "[6/9] Generating RSA keys (if not present)..."
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
else
    echo "  → Keys already exist, skipping."
fi

# ── 7. Create ML models directory ───────────────────────────────────
echo "[7/9] Setting up ML models directory..."
ML_DIR="$PROJECT_DIR/ml/models"
mkdir -p "$ML_DIR"
chown -R "$USER_NAME:$USER_NAME" "$ML_DIR"

if [ ! -f "$ML_DIR/svm_model.pkl" ]; then
    echo "  → No pre-trained models found."
    echo "  → Train models: cd $PROJECT_DIR && $VENV_DIR/bin/python -m ml.train_models"
fi

# ── 8. Create evidence directories ──────────────────────────────────
echo "[8/9] Creating evidence directory structure..."
mkdir -p "$USB_MOUNT/evidence"
chown -R "$USER_NAME:$USER_NAME" "$USB_MOUNT/evidence" 2>/dev/null || true

# Fallback local evidence dir if USB not mounted
mkdir -p "$PROJECT_DIR/evidence_local"
chown -R "$USER_NAME:$USER_NAME" "$PROJECT_DIR/evidence_local"

# ── 9. Install systemd service ──────────────────────────────────────
echo "[9/9] Installing systemd service..."
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
echo " Evidence : $USB_MOUNT/evidence"
echo " Dashboard: http://$HOSTNAME.local:5000"
echo ""
echo " To start now:   sudo systemctl start $SERVICE_NAME"
echo " To run interactive: cd $PROJECT_DIR && $VENV_DIR/bin/python main_node2.py --mode interactive"
echo " To train ML:    cd $PROJECT_DIR && $VENV_DIR/bin/python -m ml.train_models"
echo ""
echo " NOTE: Copy the same crypto_keys/ folder from Pi 1 for shared encryption."
echo " NOTE: Set up LUKS USB with: sudo bash scripts/setup_luks.sh /dev/sdX"
echo ""
