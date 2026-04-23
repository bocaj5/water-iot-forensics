"""
CoAP sensor client for Raspberry Pi 2 (Forensic Guardian node).
Receives sensor data from Pi 1 via secure CoAP/DTLS.
"""

import logging
import json
from typing import List, Dict, Optional, Callable
from datetime import datetime
from collections import deque
import threading

from .sensor_types import SensorReading

logger = logging.getLogger(__name__)


class CoAPSensorClient:
    """CoAP client for receiving sensor data from Sensor Gateway node."""

    def __init__(self, node_id: str = "pi2", sensor_gateway_ip: str = "192.168.1.10"):
        """
        Initialize CoAP sensor client.

        Args:
            node_id: Node identifier (typically 'pi2' for Forensic Guardian)
            sensor_gateway_ip: IP address of Sensor Gateway (Pi 1)
        """
        self.node_id = node_id
        self.sensor_gateway_ip = sensor_gateway_ip
        self.coap_port = 5683  # Standard CoAP port
        self.is_connected = False

        # Received data buffer
        self.received_readings = deque(maxlen=43200)  # 12 hours buffer

        # Callbacks for data reception
        self.on_data_received: Optional[Callable] = None
        self.on_connection_lost: Optional[Callable] = None

        # Threading
        self.receive_thread = None
        self.is_running = False
        self.lock = threading.Lock()

        logger.info(f"CoAP Sensor Client initialized on {node_id}")
        logger.info(f"Target: {sensor_gateway_ip}:{self.coap_port}")

    def connect(self) -> bool:
        """
        Connect to Sensor Gateway via CoAP/DTLS.

        Returns:
            True if connection successful
        """
        try:
            # In production, this would use actual CoAP library
            # For now, simulating connection
            logger.info(f"Connecting to {self.sensor_gateway_ip}...")

            # Simulate connection handshake
            self.is_connected = True
            logger.info("CoAP/DTLS connection established")

            return True

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            self.is_connected = False
            return False

    def start_listening(self):
        """Start listening for sensor data from Pi 1."""
        if self.is_running:
            logger.warning("Already listening for data")
            return

        if not self.is_connected:
            logger.error("Not connected. Call connect() first.")
            return

        self.is_running = True
        self.receive_thread = threading.Thread(
            target=self._receive_loop,
            daemon=True
        )
        self.receive_thread.start()
        logger.info("Listening for sensor data from Pi 1...")

    def stop_listening(self):
        """Stop listening for sensor data."""
        self.is_running = False
        if self.receive_thread:
            self.receive_thread.join(timeout=5.0)
        logger.info("Stopped listening for sensor data")

    def _receive_loop(self):
        """Main receive loop - simulated for testing."""
        import time
        import random

        while self.is_running:
            try:
                # Simulate receiving data from Pi 1
                readings_data = self._simulate_coap_receive()

                if readings_data:
                    with self.lock:
                        for reading_dict in readings_data:
                            reading = SensorReading.from_dict(reading_dict)
                            self.received_readings.append(reading)

                    # Call callback if set
                    if self.on_data_received:
                        self.on_data_received(readings_data)

                    logger.debug(f"Received {len(readings_data)} readings from Pi 1")

            except Exception as e:
                logger.error(f"Error in receive loop: {e}")
                self.is_connected = False
                if self.on_connection_lost:
                    self.on_connection_lost()

            time.sleep(5.0)  # Receive every 5 seconds

    def _simulate_coap_receive(self) -> Optional[List[Dict]]:
        """Simulate receiving CoAP data (for testing)."""
        import random
        from datetime import datetime

        # Simulated sensor readings
        readings = [
            {
                'sensor_id': 'ph_gpio4',
                'sensor_type': 'pH',
                'value': 7.0 + random.gauss(0, 0.3),
                'unit': 'pH',
                'timestamp': datetime.now().isoformat(),
                'node_id': 'pi1',
                'raw_value': 7.0 + random.gauss(0, 0.3),
                'confidence': 0.95
            },
            {
                'sensor_id': 'chlorine_gpio17',
                'sensor_type': 'Chlorine',
                'value': 1.0 + random.gauss(0, 0.2),
                'unit': 'mg/L',
                'timestamp': datetime.now().isoformat(),
                'node_id': 'pi1',
                'raw_value': 1.0 + random.gauss(0, 0.2),
                'confidence': 0.95
            },
            {
                'sensor_id': 'temp_gpio27',
                'sensor_type': 'Temperature',
                'value': 20.0 + random.gauss(0, 1.5),
                'unit': '°C',
                'timestamp': datetime.now().isoformat(),
                'node_id': 'pi1',
                'raw_value': 20.0 + random.gauss(0, 1.5),
                'confidence': 0.98
            }
        ]

        return readings

    def get_recent_readings(self, count: int = 10) -> List[SensorReading]:
        """Get recent readings received from Pi 1."""
        with self.lock:
            readings_list = list(self.received_readings)
            return readings_list[-count:] if count else readings_list

    def get_readings_by_type(self, sensor_type: str) -> List[SensorReading]:
        """Get all readings of a specific sensor type."""
        with self.lock:
            return [r for r in self.received_readings if r.sensor_type == sensor_type]

    def send_command_to_gateway(self, command: str, params: Dict = None) -> bool:
        """
        Send command to Sensor Gateway via CoAP.

        Args:
            command: Command name (e.g., 'calibrate', 'reset')
            params: Command parameters

        Returns:
            True if sent successfully
        """
        if not self.is_connected:
            logger.error("Not connected to gateway")
            return False

        try:
            command_msg = {
                'command': command,
                'params': params or {},
                'timestamp': datetime.now().isoformat()
            }
            logger.info(f"Sending command to Pi 1: {command}")
            # In production, would send via CoAP
            return True
        except Exception as e:
            logger.error(f"Error sending command: {e}")
            return False

    def get_gateway_status(self) -> Dict:
        """Get status from Sensor Gateway."""
        if not self.is_connected:
            return {'status': 'disconnected'}

        # In production, would query via CoAP
        return {
            'status': 'connected',
            'gateway_ip': self.sensor_gateway_ip,
            'last_read': datetime.now().isoformat(),
            'is_listening': self.is_running
        }
