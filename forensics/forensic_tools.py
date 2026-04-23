#!/usr/bin/env python3
"""
Forensic analysis CLI tools.

Provides investigators with:
  • Evidence decryption (requires RSA private key)
  • Hash chain integrity verification
  • Attack timeline reconstruction
  • Chain of custody audit
  • Evidence export (JSON / CSV)

Usage:
    python -m forensics.forensic_tools verify    --evidence-dir /mnt/encrypted_usb/evidence
    python -m forensics.forensic_tools decrypt   --evidence-id <UUID> --key crypto_keys/forensic_private.pem
    python -m forensics.forensic_tools timeline  --evidence-dir /mnt/encrypted_usb/evidence
    python -m forensics.forensic_tools custody   --evidence-id <UUID>
    python -m forensics.forensic_tools export    --evidence-dir /mnt/encrypted_usb/evidence --format json
    python -m forensics.forensic_tools export    --evidence-dir /mnt/encrypted_usb/evidence --format csv
"""

import sys
import json
import csv
import hashlib
import argparse
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ForensicTools')


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_evidence_index(evidence_dir: Path) -> List[Dict]:
    """Load all evidence JSON files from an evidence directory."""
    items = []
    for f in sorted(evidence_dir.glob('*.json')):
        if f.name.startswith('.') or 'chain_of_custody' in f.name:
            continue
        try:
            with open(f) as fh:
                items.append(json.load(fh))
        except Exception as e:
            logger.warning(f"Could not read {f.name}: {e}")
    return items


def load_custody_log(evidence_dir: Path) -> List[Dict]:
    """Load chain of custody JSONL log."""
    log_file = evidence_dir / 'chain_of_custody.jsonl'
    entries = []
    if not log_file.exists():
        return entries
    with open(log_file) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


# ── Command: verify ───────────────────────────────────────────────────────────

def cmd_verify(evidence_dir: Path, verbose: bool = False) -> int:
    """Verify hash chain integrity of all evidence in the directory."""
    items = load_evidence_index(evidence_dir)
    if not items:
        print(f"No evidence found in {evidence_dir}")
        return 1

    print(f"\nHash Chain Verification Report")
    print(f"Evidence directory: {evidence_dir}")
    print(f"Evidence items found: {len(items)}")
    print("=" * 72)

    # Sort by timestamp
    items.sort(key=lambda e: e.get('timestamp_unix', 0))

    pass_count = fail_count = 0
    prev_hash = '0' * 64

    for item in items:
        eid = item.get('evidence_id', 'unknown')[:12]
        ts  = item.get('timestamp_iso', '--')
        recorded_hash    = item.get('evidence_hash', '')
        recorded_prev    = item.get('previous_hash', '')
        chain_valid      = item.get('hash_chain_valid', False)

        # Check previous hash linkage
        prev_match = (recorded_prev == prev_hash)
        overall_ok = chain_valid and prev_match

        status = "PASS" if overall_ok else "FAIL"
        if overall_ok:
            pass_count += 1
        else:
            fail_count += 1

        print(f"[{status}] {eid}... | {ts[:19]} | hash_valid={chain_valid} | chain_linked={prev_match}")
        if verbose and not overall_ok:
            print(f"       Expected prev_hash: {prev_hash[:16]}...")
            print(f"       Recorded prev_hash: {recorded_prev[:16]}...")

        prev_hash = recorded_hash if recorded_hash else prev_hash

    print("=" * 72)
    print(f"Result: {pass_count} PASSED, {fail_count} FAILED out of {len(items)} items")
    print(f"Chain integrity: {'INTACT' if fail_count == 0 else 'COMPROMISED'}")

    return 0 if fail_count == 0 else 2


# ── Command: decrypt ──────────────────────────────────────────────────────────

def cmd_decrypt(evidence_dir: Path, evidence_id: str, private_key_path: Path) -> int:
    """Decrypt a specific encrypted evidence package."""
    if not private_key_path.exists():
        print(f"Private key not found: {private_key_path}")
        return 1

    # Find encrypted file
    enc_files = list(evidence_dir.glob(f"*{evidence_id[:8]}*.enc.json"))
    if not enc_files:
        enc_files = list(evidence_dir.glob(f"{evidence_id}.enc.json"))
    if not enc_files:
        print(f"No encrypted evidence file found for ID: {evidence_id}")
        return 1

    enc_file = enc_files[0]
    print(f"Decrypting: {enc_file.name}")

    try:
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend

        with open(private_key_path, 'rb') as f:
            private_key = serialization.load_pem_private_key(
                f.read(), password=None, backend=default_backend()
            )

        with open(enc_file) as f:
            enc_package = json.load(f)

        wrapped_key = bytes.fromhex(enc_package['wrapped_key'])
        iv          = bytes.fromhex(enc_package['iv'])
        ciphertext  = bytes.fromhex(enc_package['ciphertext'])

        aes_key = private_key.decrypt(
            wrapped_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        pad_len = padded[-1]
        plaintext = padded[:-pad_len]

        evidence_data = json.loads(plaintext.decode('utf-8'))

        output_path = enc_file.with_suffix('').with_suffix('.decrypted.json')
        with open(output_path, 'w') as f:
            json.dump(evidence_data, f, indent=2)

        print(f"Decryption successful.")
        print(f"Output: {output_path}")
        print(f"Evidence ID: {evidence_data.get('evidence_id', '--')}")
        print(f"Timestamp:   {evidence_data.get('timestamp_iso', '--')}")
        print(f"Anomaly:     {evidence_data.get('anomaly_data', {}).get('anomaly_type', '--')}")
        print(f"Encrypted:   {evidence_data.get('encrypted', '--')}")
        print(f"Hash valid:  {evidence_data.get('hash_chain_valid', '--')}")
        return 0

    except Exception as e:
        print(f"Decryption failed: {e}")
        return 1


# ── Command: timeline ─────────────────────────────────────────────────────────

def cmd_timeline(evidence_dir: Path) -> int:
    """Reconstruct and display an attack event timeline."""
    items = load_evidence_index(evidence_dir)
    if not items:
        print(f"No evidence found in {evidence_dir}")
        return 1

    items.sort(key=lambda e: e.get('timestamp_unix', 0))

    print(f"\nForensic Attack Timeline")
    print(f"Evidence directory: {evidence_dir}")
    print(f"Period: {items[0].get('timestamp_iso','--')[:19]}  →  {items[-1].get('timestamp_iso','--')[:19]}")
    print(f"Total anomaly events: {len(items)}")
    print("=" * 80)

    prev_ts = None
    for i, item in enumerate(items, 1):
        ts_iso    = item.get('timestamp_iso', '--')
        ts_unix   = item.get('timestamp_unix', 0)
        eid       = item.get('evidence_id', 'unknown')
        anomaly   = item.get('anomaly_data', {})
        a_type    = anomaly.get('anomaly_type', anomaly.get('type', '--'))
        sensor    = anomaly.get('sensor_type', '--')
        score     = anomaly.get('ensemble_score', anomaly.get('score', '--'))
        severity  = anomaly.get('severity', '--')
        encrypted = item.get('encrypted', False)
        chain_ok  = item.get('hash_chain_valid', False)

        gap = f"+{ts_unix - prev_ts:.1f}s" if prev_ts else "T+0"
        prev_ts = ts_unix

        print(f"\nEvent {i:>3}  [{gap:>8}]  {ts_iso[:23]}")
        print(f"  Evidence ID : {eid}")
        print(f"  Sensor      : {sensor}   Type: {a_type}   Severity: {severity}")
        print(f"  ML Score    : {score}   Encrypted: {encrypted}   Hash chain: {'OK' if chain_ok else 'FAIL'}")

    print("\n" + "=" * 80)
    print(f"Timeline contains {len(items)} forensic events.")
    print(f"Hash chain integrity: {'ALL VALID' if all(i.get('hash_chain_valid') for i in items) else 'FAILURES DETECTED'}")
    return 0


# ── Command: custody ──────────────────────────────────────────────────────────

def cmd_custody(evidence_dir: Path, evidence_id: Optional[str]) -> int:
    """Display chain of custody audit trail for one or all evidence items."""
    entries = load_custody_log(evidence_dir)
    if not entries:
        print(f"No chain of custody log found in {evidence_dir}")
        return 1

    if evidence_id:
        entries = [e for e in entries if e.get('evidence_id', '').startswith(evidence_id)]
        if not entries:
            print(f"No custody entries for evidence ID: {evidence_id}")
            return 1

    print(f"\nChain of Custody Audit Trail")
    print(f"{'Evidence ID':>14}  {'Action':>14}  {'Operator':>14}  {'Timestamp':>25}  {'Hash Verified':>13}")
    print("-" * 90)
    for e in entries:
        eid = (e.get('evidence_id') or '')[:12]
        print(
            f"{eid:>14}  "
            f"{e.get('action','--'):>14}  "
            f"{e.get('operator_id','--'):>14}  "
            f"{e.get('timestamp_iso','--')[:25]:>25}  "
            f"{'YES' if e.get('hash_verified') else 'NO':>13}"
        )
    print(f"\nTotal entries: {len(entries)}")
    return 0


# ── Command: export ───────────────────────────────────────────────────────────

def cmd_export(evidence_dir: Path, output_format: str, output_path: Optional[Path]) -> int:
    """Export all evidence to JSON or CSV."""
    items = load_evidence_index(evidence_dir)
    custody = load_custody_log(evidence_dir)

    if not items:
        print(f"No evidence found in {evidence_dir}")
        return 1

    if output_format == 'json':
        default_name = f"evidence_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        out = output_path or (evidence_dir / default_name)
        export_data = {
            'export_timestamp': datetime.utcnow().isoformat(),
            'evidence_count': len(items),
            'custody_entries': len(custody),
            'evidence': items,
            'chain_of_custody': custody,
        }
        with open(out, 'w') as f:
            json.dump(export_data, f, indent=2)
        print(f"Exported {len(items)} evidence items to: {out}")

    elif output_format == 'csv':
        default_name = f"evidence_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        out = output_path or (evidence_dir / default_name)
        fieldnames = [
            'evidence_id', 'timestamp_iso', 'anomaly_type', 'sensor_type',
            'ensemble_score', 'severity', 'encrypted', 'hash_chain_valid',
            'evidence_hash', 'previous_hash',
        ]
        with open(out, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for item in items:
                anomaly = item.get('anomaly_data', {})
                writer.writerow({
                    'evidence_id':     item.get('evidence_id', ''),
                    'timestamp_iso':   item.get('timestamp_iso', ''),
                    'anomaly_type':    anomaly.get('anomaly_type', anomaly.get('type', '')),
                    'sensor_type':     anomaly.get('sensor_type', ''),
                    'ensemble_score':  anomaly.get('ensemble_score', ''),
                    'severity':        anomaly.get('severity', ''),
                    'encrypted':       item.get('encrypted', ''),
                    'hash_chain_valid': item.get('hash_chain_valid', ''),
                    'evidence_hash':   item.get('evidence_hash', ''),
                    'previous_hash':   item.get('previous_hash', ''),
                })
        print(f"Exported {len(items)} evidence items to: {out}")

    return 0


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Forensic analysis tools for water treatment IoT evidence'
    )
    parser.add_argument(
        '--evidence-dir', default='/mnt/encrypted_usb/evidence',
        help='Path to evidence directory (default: /mnt/encrypted_usb/evidence)'
    )

    sub = parser.add_subparsers(dest='command', required=True)

    # verify
    p_verify = sub.add_parser('verify', help='Verify hash chain integrity of all evidence')
    p_verify.add_argument('--verbose', action='store_true')

    # decrypt
    p_decrypt = sub.add_parser('decrypt', help='Decrypt a specific evidence file')
    p_decrypt.add_argument('--evidence-id', required=True, help='Evidence UUID (or prefix)')
    p_decrypt.add_argument('--key', default='crypto_keys/forensic_private.pem',
                           help='Path to RSA private key PEM file')

    # timeline
    sub.add_parser('timeline', help='Reconstruct attack timeline from evidence')

    # custody
    p_custody = sub.add_parser('custody', help='Display chain of custody audit trail')
    p_custody.add_argument('--evidence-id', default=None,
                           help='Filter by evidence ID (or leave blank for all)')

    # export
    p_export = sub.add_parser('export', help='Export evidence to JSON or CSV')
    p_export.add_argument('--format', choices=['json', 'csv'], default='json')
    p_export.add_argument('--output', default=None, help='Output file path')

    args = parser.parse_args()
    evidence_dir = Path(args.evidence_dir)

    if not evidence_dir.exists():
        print(f"Evidence directory not found: {evidence_dir}")
        return 1

    if args.command == 'verify':
        return cmd_verify(evidence_dir, getattr(args, 'verbose', False))

    elif args.command == 'decrypt':
        return cmd_decrypt(evidence_dir, args.evidence_id, Path(args.key))

    elif args.command == 'timeline':
        return cmd_timeline(evidence_dir)

    elif args.command == 'custody':
        return cmd_custody(evidence_dir, getattr(args, 'evidence_id', None))

    elif args.command == 'export':
        output = Path(args.output) if getattr(args, 'output', None) else None
        return cmd_export(evidence_dir, args.format, output)

    return 0


if __name__ == '__main__':
    sys.exit(main())
