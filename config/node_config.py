"""
Node-specific configuration for dual Pi system.
Each node (Pi 1 and Pi 2) has its own configuration profile.
"""

from dataclasses import dataclass
from typing import Optional, Dict
import json
import os


@dataclass
class NodeConfig:
    """Configuration for a single node in the dual Pi system."""

    # Node identity
    node_id: str  # 'pi1' or 'pi2'
    node_role: str  # 'sensor_gateway' or 'forensic_guardian'

    # GPIO configuration (Pi 1 only)
    gpio_pins: Optional[Dict[str, int]] = None  # {'ph': 4, 'chlorine': 17, 'temp': 27}

    # Network configuration
    hostname: str = "localhost"
    listen_port: int = 5683  # CoAP port
    remote_host: Optional[str] = None  # Other node's IP
    remote_port: int = 5683

    # Security
    use_dtls: bool = True
    certificate_file: Optional[str] = None
    private_key_file: Optional[str] = None

    # Sensor configuration
    sensor_read_interval: float = 5.0  # seconds
    data_transmission_interval: float = 5.0  # seconds
    buffer_hours: int = 12  # local data buffer size

    # Evidence storage (Pi 2 only)
    evidence_dir: str = "/mnt/encrypted_usb/evidence"
    evidence_retention_days: int = 365

    # Logging
    log_level: str = "INFO"
    log_file: Optional[str] = None

    # Features
    enable_heartbeat: bool = True
    heartbeat_interval: float = 60.0
    enable_anomaly_detection: bool = True

    def to_dict(self) -> Dict:
        """Convert config to dictionary."""
        return {
            'node_id': self.node_id,
            'node_role': self.node_role,
            'gpio_pins': self.gpio_pins,
            'hostname': self.hostname,
            'listen_port': self.listen_port,
            'remote_host': self.remote_host,
            'remote_port': self.remote_port,
            'use_dtls': self.use_dtls,
            'certificate_file': self.certificate_file,
            'private_key_file': self.private_key_file,
            'sensor_read_interval': self.sensor_read_interval,
            'data_transmission_interval': self.data_transmission_interval,
            'buffer_hours': self.buffer_hours,
            'evidence_dir': self.evidence_dir,
            'evidence_retention_days': self.evidence_retention_days,
            'log_level': self.log_level,
            'log_file': self.log_file,
            'enable_heartbeat': self.enable_heartbeat,
            'heartbeat_interval': self.heartbeat_interval,
            'enable_anomaly_detection': self.enable_anomaly_detection
        }

    def to_json(self) -> str:
        """Convert config to JSON."""
        return json.dumps(self.to_dict(), indent=2)

    @staticmethod
    def from_dict(data: Dict) -> 'NodeConfig':
        """Create config from dictionary."""
        return NodeConfig(
            node_id=data.get('node_id'),
            node_role=data.get('node_role'),
            gpio_pins=data.get('gpio_pins'),
            hostname=data.get('hostname', 'localhost'),
            listen_port=data.get('listen_port', 5683),
            remote_host=data.get('remote_host'),
            remote_port=data.get('remote_port', 5683),
            use_dtls=data.get('use_dtls', True),
            certificate_file=data.get('certificate_file'),
            private_key_file=data.get('private_key_file'),
            sensor_read_interval=data.get('sensor_read_interval', 5.0),
            data_transmission_interval=data.get('data_transmission_interval', 5.0),
            buffer_hours=data.get('buffer_hours', 12),
            evidence_dir=data.get('evidence_dir', '/mnt/encrypted_usb/evidence'),
            evidence_retention_days=data.get('evidence_retention_days', 365),
            log_level=data.get('log_level', 'INFO'),
            log_file=data.get('log_file'),
            enable_heartbeat=data.get('enable_heartbeat', True),
            heartbeat_interval=data.get('heartbeat_interval', 60.0),
            enable_anomaly_detection=data.get('enable_anomaly_detection', True)
        )


def get_pi1_config() -> NodeConfig:
    """Get configuration for Sensor Gateway (Pi 1)."""
    return NodeConfig(
        node_id='pi1',
        node_role='sensor_gateway',
        gpio_pins={
            'ph': 4,
            'chlorine': 17,
            'temperature': 27
        },
        hostname='water-pi1',
        listen_port=5683,
        remote_host='192.168.1.11',
        remote_port=5683,
        sensor_read_interval=5.0,
        data_transmission_interval=5.0,
        buffer_hours=12,
        enable_heartbeat=True,
        enable_anomaly_detection=False  # Light detection only on Pi 1
    )


def get_pi2_config() -> NodeConfig:
    """Get configuration for Forensic Guardian (Pi 2)."""
    return NodeConfig(
        node_id='pi2',
        node_role='forensic_guardian',
        hostname='water-pi2',
        listen_port=5683,
        remote_host='192.168.1.10',
        remote_port=5683,
        evidence_dir='/mnt/encrypted_usb/evidence',
        evidence_retention_days=365,
        enable_heartbeat=True,
        enable_anomaly_detection=True  # Full ML analysis on Pi 2
    )


def load_config_from_file(filepath: str) -> NodeConfig:
    """Load configuration from JSON file."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Config file not found: {filepath}")

    with open(filepath, 'r') as f:
        data = json.load(f)

    return NodeConfig.from_dict(data)


def save_config_to_file(config: NodeConfig, filepath: str):
    """Save configuration to JSON file."""
    with open(filepath, 'w') as f:
        f.write(config.to_json())
