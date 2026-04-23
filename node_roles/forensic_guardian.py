"""
Forensic Guardian Node (Raspberry Pi 2) - Main logic for analysis and evidence collection.
Receives sensor data from Pi 1, runs ML analysis, and collects forensic evidence.
"""

import logging
import threading
import time
from collections import deque
from typing import Dict, Optional, List
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class ForensicGuardianNode:
    """
    Forensic Guardian Node running on Raspberry Pi 2.

    Responsibilities:
    - Receive sensor data from Pi 1 via CoAP
    - Run ML anomaly detection (SVM + LSTM ensemble)
    - Collect and store forensic evidence on encrypted USB
    - Maintain chain of custody
    - Send alerts on anomalies
    """

    def __init__(self,
                 node_id: str = "pi2",
                 coap_port: int = 5683,
                 evidence_dir: str = "/mnt/encrypted_usb/evidence",
                 svm_model: str = None,
                 lstm_model: str = None):
        self.node_id = node_id
        self.coap_port = coap_port
        self.evidence_dir = evidence_dir

        # Sensor client for simulation / fallback receive
        from iot_sensors.sensor_driver_coap import CoAPSensorClient
        self.sensor_client = CoAPSensorClient(
            node_id=node_id,
            sensor_gateway_ip="192.168.1.10"
        )

        # Real CoAP server
        from coap.coap_server import CoAPServer
        self.coap_server = CoAPServer(
            port=coap_port,
            on_data_received=self._on_sensor_data_received,
        )

        # ML anomaly detection engine
        from anomaly_detection.engine import AnomalyDetectionEngine
        model_dir = Path(__file__).resolve().parent.parent / 'ml' / 'models'
        self.anomaly_engine = AnomalyDetectionEngine(
            svm_model_file=svm_model or str(model_dir / 'svm_model.pkl'),
            lstm_model_file=lstm_model or str(model_dir / 'lstm_autoencoder.tflite'),
        )
        self.anomaly_engine.set_anomaly_callback(self._on_anomaly_detected)

        # Forensic evidence collector + chain of custody
        from config.crypto_manager import CryptoManager
        from forensics.forensic_collector import ForensicCollector
        from forensics.chain_of_custody import ChainOfCustodyManager

        self.crypto = CryptoManager()
        self.evidence_collector = ForensicCollector(
            evidence_dir=evidence_dir,
            crypto_manager=self.crypto,
        )
        self.custody_manager = ChainOfCustodyManager(evidence_dir=evidence_dir)

        # Incoming readings buffer (thread-safe)
        self._incoming_readings: List[Dict] = []
        self._readings_lock = threading.Lock()

        # Rolling buffer of processed readings for the dashboard API
        self._recent_readings: deque = deque(maxlen=500)

        # State
        self.is_running = False
        self.server_active = False
        self.is_receiving_data = False

        self.stats = {
            'data_packets_received': 0,
            'anomalies_detected': 0,
            'evidence_items_collected': 0,
            'last_anomaly_time': None,
            'anomaly_types': {}
        }

        self.analysis_thread = None
        self.lock = threading.Lock()

        logger.info(f"Forensic Guardian Node initialized: {node_id}")
        logger.info(f"CoAP server port: {coap_port}")
        logger.info(f"Evidence directory: {evidence_dir}")

    def start(self):
        """Start the Forensic Guardian node."""
        if self.is_running:
            logger.warning("Guardian already running")
            return

        logger.info("Starting Forensic Guardian Node...")

        # Start real CoAP server
        self.coap_server.start()
        self.server_active = True
        logger.info("CoAP server started")

        # Connect the simulation client so get_recent_readings() can be used
        # as a fallback in _analysis_loop — but do NOT start its receive loop,
        # which would feed duplicate/simulated readings alongside real CoAP data.
        if self.sensor_client.connect():
            logger.info("Sensor client connected (simulation fallback available)")

        # Start analysis thread
        self.is_running = True
        self.analysis_thread = threading.Thread(
            target=self._analysis_loop,
            daemon=True,
        )
        self.analysis_thread.start()
        logger.info("Forensic Guardian Node started")

    def stop(self):
        """Stop the Forensic Guardian node."""
        logger.info("Stopping Forensic Guardian Node...")
        self.is_running = False
        self.sensor_client.stop_listening()
        self.coap_server.stop()

        if self.analysis_thread:
            self.analysis_thread.join(timeout=5.0)
        logger.info("Forensic Guardian Node stopped")

    # ── Data reception ────────────────────────────────────────────────────────

    def _on_sensor_data_received(self, readings_data: List[Dict]):
        """Callback from CoAP server or sensor client when data arrives."""
        with self._readings_lock:
            self._incoming_readings.extend(readings_data)
        with self.lock:
            self.stats['data_packets_received'] += len(readings_data)
        self.is_receiving_data = True
        logger.debug(f"Received {len(readings_data)} sensor readings")

    # ── Analysis loop ─────────────────────────────────────────────────────────

    def _analysis_loop(self):
        """Main loop: pull incoming readings, run ML, collect evidence."""
        while self.is_running:
            try:
                # Drain incoming buffer
                with self._readings_lock:
                    batch = list(self._incoming_readings)
                    self._incoming_readings.clear()

                # If no CoAP data, try the simulation client
                if not batch:
                    sim_readings = self.sensor_client.get_recent_readings(count=3)
                    batch = [r.to_dict() for r in sim_readings] if sim_readings else []

                for reading_dict in batch:
                    sensor_type = reading_dict.get('sensor_type', '')
                    value = reading_dict.get('value')
                    if value is None:
                        continue
                    self._recent_readings.append(reading_dict)
                    self.anomaly_engine.process_reading(
                        sensor_type, float(value), reading_dict
                    )

            except Exception as e:
                logger.error(f"Error in analysis loop: {e}")

            time.sleep(5.0)

    # ── Anomaly callback ──────────────────────────────────────────────────────

    def _on_anomaly_detected(self, anomaly_result, reading_dict: Dict):
        """Called by AnomalyDetectionEngine when an anomaly is detected."""
        try:
            # Grab recent readings for context
            recent = self.sensor_client.get_recent_readings(count=10)
            readings_list = [r.to_dict() for r in recent] if recent else [reading_dict]

            # Collect forensic evidence
            evidence = self.evidence_collector.collect_evidence(
                anomaly_data=anomaly_result.to_dict(),
                sensor_readings=readings_list,
            )

            if evidence:
                # Log chain of custody
                self.custody_manager.log_action(
                    evidence_id=evidence.evidence_id,
                    action='collected',
                    operator_id=self.node_id,
                    hash_value=evidence.evidence_hash,
                    notes=f"Auto-collected: {anomaly_result.anomaly_type}",
                )

                with self.lock:
                    self.stats['evidence_items_collected'] += 1

            with self.lock:
                self.stats['anomalies_detected'] += 1
                self.stats['last_anomaly_time'] = datetime.now().isoformat()
                atype = anomaly_result.anomaly_type
                self.stats['anomaly_types'][atype] = \
                    self.stats['anomaly_types'].get(atype, 0) + 1

        except Exception as e:
            logger.error(f"Error in anomaly callback: {e}")

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        with self.lock:
            return {
                'node_id': self.node_id,
                'running': self.is_running,
                'server_active': self.server_active,
                'receiving_data': self.is_receiving_data,
                'gateway_status': self.sensor_client.get_gateway_status(),
                'coap_stats': self.coap_server.get_stats(),
                'stats': self.stats.copy(),
            }

    def get_recent_readings(self, count: int = 50) -> List[Dict]:
        """Return the last `count` sensor readings received from Pi B."""
        readings = list(self._recent_readings)
        return readings[-count:]

    def get_anomaly_summary(self) -> Dict:
        with self.lock:
            return {
                'total_anomalies': self.stats['anomalies_detected'],
                'evidence_items': self.stats['evidence_items_collected'],
                'last_anomaly': self.stats['last_anomaly_time'],
                'anomaly_types': self.stats['anomaly_types'].copy(),
            }
