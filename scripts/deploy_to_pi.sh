#!/usr/bin/env bash
# Deploy changed source files to Pi A and Pi B, then restart services.
# Usage: bash scripts/deploy_to_pi.sh
# One-time setup: on each Pi run:
#   echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFNYp9inrA2zLmXinKloMPJXHQZzi1zQS9doLTVs9J0+ mac-to-pi" >> ~/.ssh/authorized_keys
set -e

PI_A="pia@10.137.71.50"
PI_B="pib@10.137.71.51"
REMOTE_DIR="~/water-monitor"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SSH="ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no"

echo "=== Deploying to Pi A (Forensic Guardian: ${PI_A}) ==="

for f in \
    anomaly_detection/engine.py \
    iot_sensors/sensor_types.py \
    node_roles/forensic_guardian.py \
    coap/coap_security.py \
    coap/coap_server.py \
    config/coap_psk.key \
    dashboard/app.py \
    dashboard/static/js/dashboard.js \
    dashboard/static/css/style.css
do
    rsync -av --rsh="ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no" \
        "${LOCAL_DIR}/${f}" "${PI_A}:${REMOTE_DIR}/${f}"
done

echo "Restarting water-forensic-guardian..."
$SSH "${PI_A}" "sudo systemctl restart water-forensic-guardian && sudo systemctl status water-forensic-guardian --no-pager -l"

echo ""
echo "=== Deploying to Pi B (Sensor Gateway: ${PI_B}) ==="

for f in \
    iot_sensors/sensor_types.py \
    coap/coap_client.py \
    coap/coap_security.py \
    config/coap_psk.key
do
    rsync -av --rsh="ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no" \
        "${LOCAL_DIR}/${f}" "${PI_B}:${REMOTE_DIR}/${f}"
done

echo "Restarting water-sensor-gateway..."
$SSH "${PI_B}" "sudo systemctl restart water-sensor-gateway && sudo systemctl status water-sensor-gateway --no-pager -l"

echo ""
echo "Done."
