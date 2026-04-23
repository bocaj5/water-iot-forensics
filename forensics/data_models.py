"""Data models for forensic evidence and chain of custody."""

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
from enum import Enum


class AnomalyType(Enum):
    CHEMICAL_OVERDOSE = "chemical_overdose"
    ACID_INJECTION = "acid_injection"
    CHLORINE_OVERDOSE = "chlorine_overdose"
    TEMPERATURE_SPIKE = "temperature_spike"
    SENSOR_DRIFT = "sensor_drift"
    COMMUNICATION_DROPOUT = "communication_dropout"
    TIMESTAMP_ANOMALY = "timestamp_anomaly"
    MULTI_PARAMETER = "multi_parameter"
    UNKNOWN = "unknown"


@dataclass
class ForensicEvidence:
    """Forensic evidence package captured during anomaly."""
    evidence_id: str
    timestamp_unix: float
    timestamp_iso: str
    anomaly_data: Dict[str, Any]
    sensor_readings: List[Dict[str, Any]]
    memory_dump: bytes
    process_list: str
    network_connections: str
    system_logs: List[str]

    # Integrity
    evidence_hash: str = ''
    previous_hash: str = '0' * 64
    hash_chain_valid: bool = False

    # Encryption
    encrypted: bool = False
    encryption_algorithm: Optional[str] = None
    iv: Optional[bytes] = None

    # Signature
    digital_signature: Optional[bytes] = None
    signer_id: str = "forensic_system_v1"

    def to_dict(self, include_sensitive: bool = False) -> Dict[str, Any]:
        d = {
            'evidence_id': self.evidence_id,
            'timestamp_unix': self.timestamp_unix,
            'timestamp_iso': self.timestamp_iso,
            'anomaly_data': self.anomaly_data,
            'sensor_readings': self.sensor_readings,
            'evidence_hash': self.evidence_hash,
            'previous_hash': self.previous_hash,
            'hash_chain_valid': self.hash_chain_valid,
            'encrypted': self.encrypted,
            'encryption_algorithm': self.encryption_algorithm,
            'signer_id': self.signer_id,
        }
        if include_sensitive:
            d['memory_dump_size'] = len(self.memory_dump)
            d['process_list_preview'] = self.process_list[:200]
            d['network_connections_count'] = len(self.network_connections.split('\n'))
            d['system_logs_count'] = len(self.system_logs)
        return d


@dataclass
class ChainOfCustodyEntry:
    """Chain of custody audit trail entry."""
    entry_id: str
    evidence_id: str
    timestamp_unix: float
    timestamp_iso: str
    action: str  # collected, transmitted, verified, decrypted, analyzed
    operator_id: str
    system_id: str
    hash_verified: bool
    hash_value: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
