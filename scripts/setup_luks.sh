#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# setup_luks.sh  –  Set up LUKS-encrypted USB drive for forensic evidence
# Usage:  sudo bash setup_luks.sh /dev/sdX
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

USB_MOUNT="/mnt/encrypted_usb"
MAPPER_NAME="evidence_usb"

if [ $# -lt 1 ]; then
    echo "Usage: sudo bash $0 /dev/sdX"
    echo ""
    echo "Available block devices:"
    lsblk -d -o NAME,SIZE,TYPE,MOUNTPOINT
    exit 1
fi

DEVICE="$1"

if [ ! -b "$DEVICE" ]; then
    echo "Error: $DEVICE is not a valid block device"
    exit 1
fi

echo "======================================"
echo " LUKS USB Setup for Forensic Evidence"
echo "======================================"
echo ""
echo " WARNING: This will ERASE ALL DATA on $DEVICE"
echo ""
read -p " Are you sure? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# ── 1. Format with LUKS ─────────────────────────────────────────────
echo "[1/5] Formatting $DEVICE with LUKS encryption..."
echo " You will be asked to set an encryption passphrase."
cryptsetup luksFormat --type luks2 --cipher aes-xts-plain64 --key-size 512 \
    --hash sha256 --iter-time 5000 "$DEVICE"

# ── 2. Open LUKS volume ─────────────────────────────────────────────
echo "[2/5] Opening LUKS volume..."
cryptsetup luksOpen "$DEVICE" "$MAPPER_NAME"

# ── 3. Create filesystem ────────────────────────────────────────────
echo "[3/5] Creating ext4 filesystem..."
mkfs.ext4 -L "evidence" "/dev/mapper/$MAPPER_NAME"

# ── 4. Mount ─────────────────────────────────────────────────────────
echo "[4/5] Mounting to $USB_MOUNT..."
mkdir -p "$USB_MOUNT"
mount "/dev/mapper/$MAPPER_NAME" "$USB_MOUNT"
mkdir -p "$USB_MOUNT/evidence"
chown -R pi:pi "$USB_MOUNT/evidence"

# ── 5. Create unlock script ─────────────────────────────────────────
echo "[5/5] Creating unlock helper script..."
cat > /usr/local/bin/unlock-evidence-usb << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
DEVICE="${1:-/dev/sda}"
MAPPER="evidence_usb"
MOUNT="/mnt/encrypted_usb"

if [ -b "/dev/mapper/$MAPPER" ]; then
    echo "Already unlocked. Mounting..."
else
    echo "Unlocking LUKS volume on $DEVICE..."
    cryptsetup luksOpen "$DEVICE" "$MAPPER"
fi

mkdir -p "$MOUNT"
mount "/dev/mapper/$MAPPER" "$MOUNT" 2>/dev/null || true
echo "Mounted at $MOUNT"
ls -la "$MOUNT/evidence/" 2>/dev/null || echo "Evidence directory empty."
SCRIPT
chmod +x /usr/local/bin/unlock-evidence-usb

echo ""
echo "======================================"
echo " LUKS Setup Complete"
echo "======================================"
echo ""
echo " Mounted at: $USB_MOUNT"
echo " Evidence:   $USB_MOUNT/evidence/"
echo ""
echo " After reboot, unlock with:"
echo "   sudo unlock-evidence-usb $DEVICE"
echo ""
echo " To lock:"
echo "   sudo umount $USB_MOUNT"
echo "   sudo cryptsetup luksClose $MAPPER_NAME"
echo ""
