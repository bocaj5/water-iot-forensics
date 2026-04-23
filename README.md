# Water Treatment IoT Forensic Monitoring System

A multi-layer forensic monitoring system for water treatment plants using two Raspberry Pi devices, machine learning-based anomaly detection, and cryptographically-secured evidence collection.

**Current Deployment Status**: LIVE — both Pis operational on 10.137.71.x network (as of 21 April 2026)

## 📋 Table of Contents

- [System Overview](#system-overview)
- [Hardware Requirements](#hardware-requirements)
- [Quick Start](#quick-start)
- [Network Setup](#network-setup)
- [Installation](#installation)
  - [Pi B: Sensor Gateway](#pi-b-sensor-gateway)
  - [Pi A: Forensic Guardian](#pi-a-forensic-guardian)
  - [LUKS Encrypted USB](#luks-encrypted-usb)
- [ML Models](#ml-models)
- [Starting the System](#starting-the-system)
- [Accessing the Dashboard](#accessing-the-dashboard)
- [Running Tests](#running-tests)
- [Forensic Tools](#forensic-tools)
- [Troubleshooting](#troubleshooting)
- [Security Notes](#security-notes)
- [Project Structure](#project-structure)

## 🏗️ System Overview

This system uses two Raspberry Pi devices on the same local network:

```
┌─────────────────────────────────────────┐
│  Pi B (Raspberry Pi 2B) — Sensor        │
│  Gateway [pib@10.137.71.51]             │
│                                         │
│  • GPIO: pH, Chlorine, Temperature     │
│  • 12-hour local buffer                │
│  • CoAP client (UDP → Pi A)             │
│  • Heartbeat monitor                    │
└─────────────────┬───────────────────────┘
                  │ CoAP (UDP:5683)
                  │ Every 5 seconds
                  ▼
┌─────────────────────────────────────────┐
│  Pi A (Raspberry Pi 4B) — Forensic      │
│  Guardian [pia@10.137.71.50]            │
│                                         │
│  • CoAP server (UDP:5683)               │
│  • ML Anomaly Detection (SVM + LSTM)    │
│  • Evidence encryption & storage        │
│  • Chain of custody logging             │
│  • Web dashboard (HTTP:5000)            │
│  • LUKS2-encrypted USB evidence storage │
└─────────────────────────────────────────┘
```

**Data Flow:**
```
[Sensors/Sim] → [Pi B: GPIO/sim → CoAP client] → [Pi A: CoAP server → ML engine]
                                                         ↓
                                                  [Anomaly detected?]
                                                   Yes ↓
                                                  [Forensic evidence]
                                                  [Chain of custody]
                                                  [RSA-4096 + AES-256]
                                                  [LUKS USB storage]
```

## 🔧 Hardware Requirements

### Required:
- 1× Raspberry Pi 2 Model B (Sensor Gateway — Pi B)
- 1× Raspberry Pi 4 Model B (Forensic Guardian — Pi A)
- 2× microSD cards (16 GB minimum, 32 GB recommended)
- 2× power supplies (USB-C for Pi 4, micro-USB for Pi 2)
- 1× USB flash drive (LUKS-encrypted evidence storage)
- Ethernet switch/router + 2× cables

### Optional (for real sensors):
- pH sensor module (GPIO pin 4)
- Chlorine sensor module (GPIO pin 17)
- Temperature sensor (DS18B20, GPIO pin 27)
- ADC module (e.g., MCP3008)

**Note:** The system runs in **simulation mode** without sensors.

## 🚀 Quick Start

```bash
# On your Mac/Desktop: Clone and prepare
git clone <repo-url>
cd Codebase

# 1. Set up Pi B (Sensor Gateway)
scp -r . pib@10.137.71.51:~/water-monitor
ssh pib@10.137.71.51 "cd ~/water-monitor && sudo bash scripts/setup_pi1.sh"

# 2. Set up Pi A (Forensic Guardian)
scp -r . pia@10.137.71.50:~/water-monitor
ssh pia@10.137.71.50 "cd ~/water-monitor && sudo bash scripts/setup_pi2.sh"

# 3. Train ML models (desktop with TensorFlow, then copy to Pi A)
python -m ml.train_models --output-dir ml/models
scp ml/models/*.{pkl,tflite,json} pia@10.137.71.50:~/water-monitor/ml/models/

# 4. Start the system
ssh pib@10.137.71.51 "sudo systemctl start water-sensor-gateway"
ssh pia@10.137.71.50 "sudo systemctl start water-forensic-guardian"

# 5. Open dashboard
# Visit: http://10.137.71.50:5000
```

## 🌐 Network Setup

**Current Configuration:**

| Device | IP Address | Hostname | Username |
|--------|-----------|----------|----------|
| Pi B (Sensor Gateway) | 10.137.71.51 | water-pib | pib |
| Pi A (Forensic Guardian) | 10.137.71.50 | water-pia | pia |

### Configure Static IPs

Edit `/etc/dhcpcd.conf` on each Pi:

**Pi B:**
```bash
interface eth0
static ip_address=10.137.71.51/24
static routers=10.137.71.1
static domain_name_servers=10.137.71.1 8.8.8.8
```

**Pi A:**
```bash
interface eth0
static ip_address=10.137.71.50/24
static routers=10.137.71.1
static domain_name_servers=10.137.71.1 8.8.8.8
```

If using different IPs, update [`config/node_config.py`](config/node_config.py):
- `pi_a_config.remote_host` — IP of Pi A (used by Pi B for CoAP)
- `pi_b_config.remote_host` — IP of Pi B (expected source on Pi A)

## 💾 Installation

### Raspberry Pi OS Setup

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Flash **Raspberry Pi OS Lite (64-bit)** to microSD cards
3. In advanced settings:
   - Hostname: `water-pib` (Pi B) or `water-pia` (Pi A)
   - Enable SSH (key or password)
   - Username: `pi`
4. Insert cards and boot both Pis

### Pi B: Sensor Gateway

```bash
# From your Mac/Desktop
scp -i ~/.ssh/id_ed25519 -r . pib@10.137.71.51:~/water-monitor

# SSH into Pi B
ssh -i ~/.ssh/id_ed25519 pib@10.137.71.51

# Run setup script (creates venv, installs deps, enables service)
cd ~/water-monitor
sudo bash scripts/setup_pi1.sh

# Reboot to apply changes
sudo reboot
```

**Setup script does:**
- System updates + hostname configuration
- Python 3, pip, venv, I2C tools
- GPIO + I2C interface enablement
- Python virtual environment + dependencies
- RSA-4096 key generation
- systemd service installation (`water-sensor-gateway`)

### Pi A: Forensic Guardian

```bash
# From your Mac/Desktop
scp -i ~/.ssh/id_ed25519 -r . pia@10.137.71.50:~/water-monitor

# SSH into Pi A
ssh -i ~/.ssh/id_ed25519 pia@10.137.71.50

# Run setup script
cd ~/water-monitor
sudo bash scripts/setup_pi2.sh

# Reboot
sudo reboot
```

**Setup script does:**
- System updates + hostname configuration
- Python 3, pip, venv, cryptsetup, libatlas, libhdf5
- LUKS USB mount point preparation (`/mnt/encrypted_usb`)
- Python virtual environment + dependencies
- TensorFlow Lite runtime installation (ARM build)
- RSA-4096 key generation
- systemd service installation (`water-forensic-guardian`)

### LUKS Encrypted USB

Forensic evidence is stored on a LUKS2-encrypted USB drive connected to Pi A.

**Deployed Configuration:**
```
Device:      /dev/sda1
LUKS UUID:   c6f38241-6a55-4769-a91a-ec70af73b874
Mapper name: encrypted_usb
Mount point: /mnt/encrypted_usb
Evidence:    /mnt/encrypted_usb/evidence/
Encryption:  AES-XTS-plain64, 512-bit key
```

**Setup from scratch:**

```bash
# 1. Insert USB into Pi A
ssh -i ~/.ssh/id_ed25519 pia@10.137.71.50

# 2. Identify device
lsblk

# 3. Run LUKS setup (follow prompts for passphrase)
sudo bash ~/water-monitor/scripts/setup_luks.sh /dev/sda

# 4. Verify auto-unlock is configured
grep encrypted_usb /etc/crypttab /etc/fstab
```

The setup script will:
- Format with LUKS2 (AES-XTS-plain64, 512-bit)
- Create ext4 filesystem
- Mount at `/mnt/encrypted_usb`
- Create keyfile for auto-unlock: `~/water-monitor/crypto_keys/usb_keyfile`
- Configure `/etc/crypttab` and `/etc/fstab` for auto-mount on boot

**Manual unlock (if needed):**
```bash
sudo cryptsetup luksOpen \
  --key-file ~/water-monitor/crypto_keys/usb_keyfile \
  /dev/sda1 encrypted_usb
sudo mount /dev/mapper/encrypted_usb /mnt/encrypted_usb
```

### Shared Encryption Keys

Both Pis share the same RSA-4096 keypair for evidence encryption consistency.

**Keys location (on Pi A):**
```
~/water-monitor/crypto_keys/
├── forensic_private.pem    (chmod 600)
├── forensic_public.pem     (chmod 644)
└── usb_keyfile             (chmod 400)
```

**Copy public key to Pi B (if needed):**
```bash
scp -i ~/.ssh/id_ed25519 \
    pia@10.137.71.50:~/water-monitor/crypto_keys/forensic_public.pem \
    pib@10.137.71.51:~/water-monitor/crypto_keys/

ssh -i ~/.ssh/id_ed25519 pib@10.137.71.51 \
    "chmod 644 ~/water-monitor/crypto_keys/forensic_public.pem"
```

## 🤖 ML Models

The anomaly detection engine uses an **SVM + LSTM ensemble**. Models must be trained before deployment.

### Training (Desktop Recommended)

**Why desktop?** Pi 2B is too slow for LSTM training; Pi 4B takes 15–30 minutes.

```bash
# Prerequisites: Python ≥3.10, TensorFlow ≥2.16
pip install tensorflow scikit-learn numpy pandas

# Train both SVM + LSTM
cd /path/to/Codebase
python -m ml.train_models --output-dir ml/models

# Or skip LSTM if not available
python -m ml.train_models --output-dir ml/models --skip-lstm
```

**Output files:**
- `ml/models/svm_model.pkl` (~8.5 MB)
- `ml/models/lstm_autoencoder.tflite` (~1.2 MB)
- `ml/models/lstm_autoencoder.json` (architecture)

**Training time:**
- Desktop (SVM + LSTM): ~15–30 minutes
- Pi 4B (SVM only): ~2–5 minutes

### Copy Models to Pi A

```bash
scp -i ~/.ssh/id_ed25519 \
    ml/models/svm_model.pkl \
    ml/models/lstm_autoencoder.tflite \
    ml/models/lstm_autoencoder.json \
    pia@10.137.71.50:~/water-monitor/ml/models/
```

### Training on Pi A (SVM only)

```bash
ssh -i ~/.ssh/id_ed25519 pia@10.137.71.50
cd ~/water-monitor
source venv/bin/activate
python -m ml.train_models --output-dir ml/models --skip-lstm
```

**Note:** Without trained models, the system falls back to rule-based scoring (SVM only, LSTM returns 0.3).

## ▶️ Starting the System

Start Pi B first, then Pi A. Startup order is flexible — Pi B will retry connecting to Pi A.

### Option A: systemd Services (Production)

```bash
# Pi B
ssh pib@10.137.71.51 "sudo systemctl start water-sensor-gateway"

# Pi A (LUKS USB auto-unlocked at boot)
ssh pia@10.137.71.50 "sudo systemctl start water-forensic-guardian"

# Both services are enabled to auto-start on boot
# Rebooting both Pis is sufficient
```

### Option B: Interactive Mode (Testing/Debugging)

```bash
# Pi B
ssh -i ~/.ssh/id_ed25519 pib@10.137.71.51
cd ~/water-monitor && source venv/bin/activate
python main_node1.py --mode interactive --log-level DEBUG

# Commands: status, readings, buffer, exit
```

```bash
# Pi A
ssh -i ~/.ssh/id_ed25519 pia@10.137.71.50
cd ~/water-monitor && source venv/bin/activate
python main_node2.py --mode interactive --log-level DEBUG

# Commands: status, anomalies, readings, exit
```

### Service Management

```bash
# Check status
sudo systemctl status water-sensor-gateway          # Pi B
sudo systemctl status water-forensic-guardian       # Pi A

# View live logs
tail -f /tmp/water-sensor-gateway.log               # Pi B
tail -f /tmp/water-forensic-guardian.log            # Pi A

# Stop/Start/Restart
sudo systemctl [stop|start|restart] water-sensor-gateway
sudo systemctl [stop|start|restart] water-forensic-guardian

# Disable auto-start
sudo systemctl disable water-sensor-gateway
sudo systemctl disable water-forensic-guardian
```

## 📊 Accessing the Dashboard

The Flask web dashboard runs on **Pi A** on **port 5000**.

**URL:** `http://10.137.71.50:5000`

### Features

- **System Status** — Pi A/B health, CoAP connection, uptime
- **Live Sensor Readings** — pH, Chlorine, Temperature with Chart.js graphs
- **ML Ensemble Score Gauge** — Real-time SVM+LSTM anomaly score
  - 🟢 Green: ≤0.5 (normal)
  - 🟡 Amber: 0.5–0.75 (elevated)
  - 🔴 Red: >0.75 (anomaly)
- **Alert Banner** — Flashes on new anomalies, auto-clears on dismiss
- **Anomaly Detection Log** — Events with severity levels
- **Evidence Inventory** — Forensic evidence files with metadata
- **Auto-refresh** — 8-second refresh for charts, 30-second for evidence table

**Note:** Dashboard is optimized for low power. Charts use constrained canvas heights (120px) to reduce CPU load.

## 🧪 Running Tests

### Unit Tests (Pytest)

```bash
cd ~/water-monitor
source venv/bin/activate
pytest tests/test_unit.py -v
```

**Coverage:** ~80% across core modules

### Attack Scenario Tests

```bash
# Run all five attack scenarios through the ML engine
python -m tests.run_attack_tests \
  --svm ml/models/svm_model.pkl \
  --lstm ml/models/lstm_autoencoder.tflite \
  --output tests/results/attack_test_results.json
```

**Scenarios tested:**
1. **Acid Injection** — rapid pH drop (7.2 → <5.0)
2. **Chlorine Overdose** — chlorine spike (1.0 → 5.0 mg/L)
3. **Temperature Spike** — rapid heating (20°C → >40°C)
4. **Multi-Parameter Attack** — coordinated acid + heat
5. **Sequential Tampering** — gradual pH → Cl → Temp shift

**Expected results (with trained SVM):**
- Detection accuracy: >95%
- Detection latency: <50ms

**Output:** `tests/results/attack_test_results.json`

## 🔍 Forensic Tools

CLI tools for post-incident investigation.

```bash
cd ~/water-monitor
source venv/bin/activate
```

### Verify Hash Chain Integrity

```bash
python -m forensics.forensic_tools verify \
  --evidence-dir /mnt/encrypted_usb/evidence
```

Checks all evidence items have valid hash chain linkage.
- Exit code 0: all PASS
- Exit code 2: failures detected

### Reconstruct Attack Timeline

```bash
python -m forensics.forensic_tools timeline \
  --evidence-dir /mnt/encrypted_usb/evidence
```

Displays chronological list of forensic events with timing gaps.

### Decrypt Evidence Package

```bash
python -m forensics.forensic_tools decrypt \
  --evidence-id <UUID-prefix> \
  --key crypto_keys/forensic_private.pem \
  --evidence-dir /mnt/encrypted_usb/evidence
```

Decrypts AES-256-CBC evidence file using RSA private key.
Output saved as `<evidence_id>.decrypted.json`

### View Chain of Custody

```bash
python -m forensics.forensic_tools custody \
  --evidence-dir /mnt/encrypted_usb/evidence
```

Displays append-only audit log with all actions and operators.

### Export Evidence

```bash
# Export to JSON
python -m forensics.forensic_tools export \
  --evidence-dir /mnt/encrypted_usb/evidence \
  --format json \
  --output /tmp/evidence_export.json

# Export to CSV
python -m forensics.forensic_tools export \
  --evidence-dir /mnt/encrypted_usb/evidence \
  --format csv \
  --output /tmp/evidence_export.csv
```

## 🐛 Troubleshooting

### Pi B cannot connect to Pi A

- Check network: `ping 10.137.71.50` from Pi B
- Check Pi A service: `sudo systemctl status water-forensic-guardian`
- Check firewall: `sudo ufw allow 5683/udp`
- Verify IPs in `config/node_config.py`

### "aiocoap not installed" warnings

```bash
source venv/bin/activate
pip install aiocoap
# Note: aiocoap[all] fails on Debian 13 (DTLS deps missing)
# Install plain aiocoap instead
```

### ML models not found

```bash
# Train models on Pi A or desktop
python -m ml.train_models --output-dir ml/models

# Or copy pre-trained models from desktop
scp ml/models/*.{pkl,tflite,json} pia@10.137.71.50:~/water-monitor/ml/models/
```

Without trained models, system uses SVM fallback scoring (LSTM returns 0.3).

### LUKS USB not mounting on boot

```bash
# Check crypttab
cat /etc/crypttab | grep encrypted_usb

# Check fstab
cat /etc/fstab | grep encrypted_usb

# Manual unlock
sudo cryptsetup luksOpen \
  --key-file ~/water-monitor/crypto_keys/usb_keyfile \
  /dev/sda1 encrypted_usb
sudo mount /dev/mapper/encrypted_usb /mnt/encrypted_usb
```

### Dashboard not loading

```bash
# Check service
sudo systemctl status water-forensic-guardian

# Test port 5000
curl http://localhost:5000

# Check firewall
sudo ufw allow 5000/tcp
```

### TensorFlow / TFLite errors on Pi

```bash
# Use tflite-runtime instead of full TensorFlow
pip install tflite-runtime

# Or train on desktop and copy .tflite file to Pi A
```

If neither works, LSTM falls back to score=0.3 (no crash).

### GPIO permission errors on Pi B

```bash
# Add user to gpio group
sudo usermod -aG gpio pib

# Log out and log back in
exit
ssh pib@10.137.71.51
```

In simulation mode, GPIO errors are expected and handled gracefully.

### No sensor data appearing

- **Simulation mode:** Sensors generate synthetic data automatically
- **GPIO mode:** Check sensor_driver_gpio.py logs
- **Config:** Verify GPIO pins in `config/node_config.py`:
  - pH: pin 4
  - Chlorine: pin 17
  - Temperature: pin 27

### "This event loop is already running" error

Fixed in `coap/coap_client.py` (threading.Lock around run_until_complete).
If it reappears, check that the lock is protecting both send methods.

## 🔐 Security Notes

### CoAP Transport Security (DTLS)

**Current Status:** CoAP is deployed **WITHOUT DTLS** (plain UDP).

**Reason:** The `aiocoap[all]` package (provides DTLSSocket via tinydtls) fails to build on Debian 13 aarch64. The dtls C extension requires libssl-dev and tinydtls-dev, which are not available in compatible versions.

### Mitigation Measures

1. **Network Isolation** — Both Pis on isolated lab LAN (10.137.71.x)
2. **Application-Layer Encryption** — All forensic evidence encrypted with AES-256-CBC (RSA-4096 wrapped key) BEFORE storage
3. **Hash Chain + Signatures** — Each evidence package SHA-256 hashed with chain verification on retrieval

### Impact on Objectives

- **FR2 (DTLS)** partially met; CoAP endpoints functional, authentication/transport encryption pending compatible library
- **All other requirements (FR1, FR3–FR8)** fully met
- Consistent with academic IoT forensics research using prototype deployments

### Future Work

- Upgrade to aiocoap ≥0.4.5 when Debian 13 provides compatible tinydtls
- Alternative: Wrap CoAP with WireGuard (kernel-level UDP tunnel) for equivalent confidentiality


## 📁 Project Structure

```
Codebase/
├── README.md                     This file
├── SETUP_INSTRUCTIONS.txt        Original setup guide
├── SECRETS_MANAGEMENT.md         Secrets handling guide
├── .env.example                  Environment variables template
├── .gitignore                    Git exclusion rules
├── main_node1.py                 Entry point for Pi 1 (Sensor Gateway)
├── main_node2.py                 Entry point for Pi 2 (Forensic Guardian)
├── setup.py                      Package setup
├── requirements_pi1.txt          Dependencies for Pi 1
├── requirements_pi2.txt          Dependencies for Pi 2
│
├── config/
│   ├── node_config.py            Network IPs, GPIO pins, feature flags
│   ├── crypto_manager.py         RSA-4096 + AES-256 hybrid encryption
│   └── coap_psk.key              [IGNORED] CoAP pre-shared key
│
├── iot_sensors/
│   ├── sensor_types.py           SensorReading dataclass
│   ├── sensor_driver_gpio.py     GPIO reading + 12-hour buffer
│   └── sensor_driver_coap.py     Simulated CoAP receiver
│
├── node_roles/
│   ├── sensor_gateway.py         Pi 1 main logic
│   ├── forensic_guardian.py      Pi 2 main logic
│   └── heartbeat_monitor.py      Configurable heartbeat
│
├── anomaly_detection/
│   ├── engine.py                 SVM+LSTM ensemble
│   ├── feature_extractor.py      13 statistical features
│   ├── svm_detector.py           SVM classifier
│   └── lstm_detector.py          LSTM autoencoder
│
├── forensics/
│   ├── data_models.py            Evidence/ChainOfCustody dataclasses
│   ├── forensic_collector.py     Evidence collection & encryption
│   ├── chain_of_custody.py       Append-only custody log
│   └── forensic_tools.py         CLI investigation tools
│
├── coap/
│   ├── coap_server.py            aiocoap server (Pi A)
│   ├── coap_client.py            aiocoap client (Pi B)
│   └── coap_security.py          AES-256-GCM payload encryption
│
├── ml/
│   ├── train_models.py           Model training CLI
│   ├── convert_lstm.py           LSTM to TFLite conversion
│   └── models/                   Trained model files
│
├── dashboard/
│   ├── app.py                    Flask app + API routes
│   ├── templates/index.html      Dashboard HTML
│   └── static/
│       ├── css/style.css         Dark theme CSS
│       └── js/dashboard.js       AJAX + Chart.js
│
├── scripts/
│   ├── setup_pi1.sh              Bootstrap script for Pi 1
│   ├── setup_pi2.sh              Bootstrap script for Pi 2
│   ├── setup_luks.sh             LUKS USB encryption setup
│   ├── water-sensor-gateway.service      systemd unit
│   └── water-forensic-guardian.service   systemd unit
│
├── utils/
│   └── logging_manager.py        Centralised logging
│
└── tests/
    ├── attack_scenarios.py       Attack scenario definitions
    ├── run_attack_tests.py       Test runner
    ├── test_unit.py              Pytest unit tests (~80% coverage)
    └── test data/                Production test datasets (JSON)
```

## 📝 License & Contributing

This is a University research project (Final Year Project, 2026).

For modifications, security issues, or questions, please refer to your institution's research guidelines.

---

**Last Updated:** 21 April 2026  
**Deployment Status:** LIVE — Dual Pi system operational  
**Support:** Refer to [SETUP_INSTRUCTIONS.txt](SETUP_INSTRUCTIONS.txt) for detailed technical reference
