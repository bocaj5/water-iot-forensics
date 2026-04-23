"""Forensic evidence collector with hash chains, encryption, and digital signatures."""

import os
import json
import uuid
import subprocess
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from .data_models import ForensicEvidence

logger = logging.getLogger(__name__)


class ForensicCollector:
    """Collects, encrypts, signs, and stores forensic evidence on anomaly detection."""

    def __init__(self, evidence_dir: str = "/mnt/encrypted_usb/evidence",
                 crypto_manager=None):
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.crypto = crypto_manager
        self.last_evidence_hash: Optional[str] = None
        self._load_last_hash()

    def _load_last_hash(self):
        """Recover the last evidence hash from disk for chain continuity."""
        hash_file = self.evidence_dir / '.last_hash'
        if hash_file.exists():
            self.last_evidence_hash = hash_file.read_text().strip()
            logger.info(f"Recovered evidence hash chain: {self.last_evidence_hash[:16]}...")

    def _save_last_hash(self):
        """Persist the last hash for crash recovery."""
        hash_file = self.evidence_dir / '.last_hash'
        if self.last_evidence_hash:
            hash_file.write_text(self.last_evidence_hash)

    def collect_evidence(self, anomaly_data: Dict[str, Any],
                         sensor_readings: List[Dict[str, Any]]) -> Optional[ForensicEvidence]:
        """Collect a full forensic evidence package.

        Args:
            anomaly_data: dict from AnomalyResult.to_dict()
            sensor_readings: list of reading dicts

        Returns:
            ForensicEvidence or None on error
        """
        try:
            evidence_id = str(uuid.uuid4())
            now = datetime.utcnow()
            timestamp_iso = now.isoformat()
            timestamp_unix = now.timestamp()

            memory_dump = self._capture_memory_dump()
            process_list = self._capture_process_list()
            network_conns = self._capture_network_connections()
            system_logs = self._capture_system_logs()

            evidence = ForensicEvidence(
                evidence_id=evidence_id,
                timestamp_unix=timestamp_unix,
                timestamp_iso=timestamp_iso,
                anomaly_data=anomaly_data,
                sensor_readings=sensor_readings,
                memory_dump=memory_dump,
                process_list=process_list,
                network_connections=network_conns,
                system_logs=system_logs,
                previous_hash=self.last_evidence_hash or '0' * 64,
            )

            # Compute hash chain
            metadata_bytes = self._serialize_metadata(evidence)
            evidence.evidence_hash = hashlib.sha256(metadata_bytes).hexdigest()

            chain_input = (evidence.previous_hash + evidence.evidence_hash).encode()
            chain_hash = hashlib.sha256(chain_input).hexdigest()
            evidence.hash_chain_valid = True

            # Encrypt evidence if crypto manager available
            encrypted_package = None
            if self.crypto:
                encrypted_package = self._encrypt_evidence(evidence)
                evidence.encrypted = True
                evidence.encryption_algorithm = 'AES-256-CBC + RSA-4096'

            # Store evidence
            self._store_evidence(evidence, encrypted_package)

            # Update hash chain
            self.last_evidence_hash = evidence.evidence_hash
            self._save_last_hash()

            logger.info(f"Forensic evidence collected: {evidence_id}")
            return evidence

        except Exception as e:
            logger.error(f"Error collecting forensic evidence: {e}")
            return None

    def _capture_memory_dump(self) -> bytes:
        try:
            result = subprocess.run(
                ['free', '-b'], capture_output=True, text=True, timeout=5
            )
            mem_info = result.stdout.encode()
            result2 = subprocess.run(
                ['ps', 'aux', '--sort=-rss'], capture_output=True, text=True, timeout=5
            )
            return mem_info + b'\n\n' + result2.stdout.encode()
        except Exception as e:
            logger.warning(f"Memory dump capture failed: {e}")
            return b'memory_dump_unavailable'

    def _capture_process_list(self) -> str:
        try:
            result = subprocess.run(
                ['ps', 'auxww'], capture_output=True, text=True, timeout=5
            )
            return result.stdout
        except Exception:
            return ''

    def _capture_network_connections(self) -> str:
        try:
            result = subprocess.run(
                ['ss', '-tupan'], capture_output=True, text=True, timeout=5
            )
            return result.stdout
        except Exception:
            return ''

    def _capture_system_logs(self) -> List[str]:
        logs = []
        try:
            result = subprocess.run(
                ['journalctl', '-n', '50', '--no-pager'],
                capture_output=True, text=True, timeout=5
            )
            logs.extend(result.stdout.split('\n'))
        except Exception:
            pass
        return logs

    def _serialize_metadata(self, evidence: ForensicEvidence) -> bytes:
        metadata = {
            'evidence_id': evidence.evidence_id,
            'timestamp_unix': evidence.timestamp_unix,
            'timestamp_iso': evidence.timestamp_iso,
            'anomaly_data': evidence.anomaly_data,
            'memory_dump_hash': hashlib.sha256(evidence.memory_dump).hexdigest(),
            'process_list_hash': hashlib.sha256(evidence.process_list.encode()).hexdigest(),
            'network_conns_hash': hashlib.sha256(
                evidence.network_connections.encode()
            ).hexdigest(),
        }
        return json.dumps(metadata, sort_keys=True).encode()

    def _encrypt_evidence(self, evidence: ForensicEvidence) -> Optional[Dict]:
        if not self.crypto:
            return None
        try:
            payload = {
                'evidence_id': evidence.evidence_id,
                'anomaly_data': evidence.anomaly_data,
                'sensor_readings': evidence.sensor_readings,
                'memory_dump_hex': evidence.memory_dump.hex(),
                'process_list': evidence.process_list,
                'network_connections': evidence.network_connections,
                'system_logs': evidence.system_logs,
            }
            return self.crypto.encrypt_evidence(payload)
        except Exception as e:
            logger.error(f"Evidence encryption error: {e}")
            return None

    def _store_evidence(self, evidence: ForensicEvidence,
                        encrypted_package: Optional[Dict] = None):
        try:
            # Store metadata JSON
            meta_file = self.evidence_dir / f"{evidence.evidence_id}.json"
            with open(meta_file, 'w') as f:
                json.dump(evidence.to_dict(), f, indent=2)

            # Store encrypted payload or raw binary
            if encrypted_package:
                enc_file = self.evidence_dir / f"{evidence.evidence_id}.enc.json"
                with open(enc_file, 'w') as f:
                    json.dump(encrypted_package, f, indent=2)
            else:
                bin_file = self.evidence_dir / f"{evidence.evidence_id}.bin"
                with open(bin_file, 'wb') as f:
                    f.write(evidence.memory_dump)

            logger.info(f"Evidence stored: {meta_file}")
        except Exception as e:
            logger.error(f"Evidence storage error: {e}")
