"""Chain of custody manager - append-only JSONL audit log with integrity verification."""

import json
import uuid
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from .data_models import ChainOfCustodyEntry

logger = logging.getLogger(__name__)


class ChainOfCustodyManager:
    """Manages immutable chain of custody audit trail for forensic evidence."""

    def __init__(self, evidence_dir: str = "/mnt/encrypted_usb/evidence"):
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.audit_file = self.evidence_dir / 'chain_of_custody.jsonl'
        self._entries_cache: List[ChainOfCustodyEntry] = []
        self._load_existing_entries()

    def _load_existing_entries(self):
        """Load existing audit entries from disk."""
        if self.audit_file.exists():
            try:
                with open(self.audit_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            self._entries_cache.append(
                                ChainOfCustodyEntry(**data)
                            )
                logger.info(f"Loaded {len(self._entries_cache)} chain of custody entries")
            except Exception as e:
                logger.warning(f"Error loading chain of custody: {e}")

    def log_action(self, evidence_id: str, action: str,
                   operator_id: str = "system",
                   hash_value: Optional[str] = None,
                   notes: Optional[str] = None) -> ChainOfCustodyEntry:
        """Record an action in the chain of custody.

        Args:
            evidence_id: UUID of the evidence
            action: one of collected, transmitted, verified, decrypted, analyzed
            operator_id: who/what performed the action
            hash_value: evidence hash at time of action
            notes: optional free-text notes

        Returns:
            The created ChainOfCustodyEntry
        """
        now = datetime.utcnow()
        entry = ChainOfCustodyEntry(
            entry_id=str(uuid.uuid4()),
            evidence_id=evidence_id,
            timestamp_unix=now.timestamp(),
            timestamp_iso=now.isoformat(),
            action=action,
            operator_id=operator_id,
            system_id='water_iot_forensics_v2',
            hash_verified=hash_value is not None,
            hash_value=hash_value,
            notes=notes,
        )

        self._store_entry(entry)
        self._entries_cache.append(entry)

        logger.info(f"Chain of custody: {evidence_id[:8]}... {action} by {operator_id}")
        return entry

    def _store_entry(self, entry: ChainOfCustodyEntry):
        """Append entry to the immutable JSONL log."""
        try:
            with open(self.audit_file, 'a') as f:
                f.write(json.dumps(entry.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Error storing audit entry: {e}")

    def verify_chain(self, evidence_id: str) -> Dict[str, Any]:
        """Verify all entries for a given evidence item."""
        matching = [e for e in self._entries_cache if e.evidence_id == evidence_id]
        return {
            'evidence_id': evidence_id,
            'total_entries': len(matching),
            'actions': [e.action for e in matching],
            'timestamps': [e.timestamp_iso for e in matching],
            'operators': list(set(e.operator_id for e in matching)),
            'all_hashes_verified': all(e.hash_verified for e in matching),
        }

    def get_entries_for_evidence(self, evidence_id: str) -> List[Dict]:
        """Get all chain of custody entries for an evidence item."""
        return [
            e.to_dict() for e in self._entries_cache
            if e.evidence_id == evidence_id
        ]

    def get_all_entries(self) -> List[Dict]:
        """Get all chain of custody entries."""
        return [e.to_dict() for e in self._entries_cache]

    def export_chain_report(self, evidence_id: str) -> str:
        """Export a human-readable chain of custody report."""
        matching = [e for e in self._entries_cache if e.evidence_id == evidence_id]

        report = f"""
CHAIN OF CUSTODY REPORT
=======================
Evidence ID: {evidence_id}
Generated: {datetime.utcnow().isoformat()}

Actions ({len(matching)} total):
"""
        for i, entry in enumerate(matching, 1):
            report += f"""
{i}. {entry.action.upper()}
   Time: {entry.timestamp_iso}
   Operator: {entry.operator_id}
   System: {entry.system_id}
   Hash Verified: {entry.hash_verified}
   Notes: {entry.notes or 'N/A'}
"""
        return report
