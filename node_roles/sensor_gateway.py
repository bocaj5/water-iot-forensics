"""
Sensor Gateway Node (Raspberry Pi 1) - Main logic for data collection and transmission.
Reads sensors via GPIO, buffers data locally, and sends to Forensic Guardian via CoAP.
"""

import logging
import threading
import time
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SensorGatewayNode:
    """
    Sensor Gateway Node running on Raspberry Pi 1.

    Responsibilities:
    - Read sensors via GPIO (pH, Chlorine, Temperature)
    - Validate sensor readings
    - Buffer data locally (12 hour capacity)
    - Send encrypted data to Pi 2 via CoAP/DTLS
    - Handle network failures gracefully
    """

    def __init__(self, 
                 node_id: str = "pi1",
                 gateway_host: str = "192.168.1.11",
                 gateway_port: int = 5683):
        self.node_id = node_id
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port

        # Sensor driver (GPIO / simulated)
        from iot_sensors.sensor_driver_gpio import GPIOSensorDriver
        self.sensor_driver = GPIOSensorDriver(node_id=node_id)

        # Real CoAP client for transmitting to Pi 2
        from coap.coap_client import CoAPClient
        self.coap_client = CoAPClient(
            server_host=gateway_host,
            server_port=gateway_port,
        )

        # State tracking
        self.is_running = False
        self.is_connected_to_gateway = False
        self.last_transmission_time = None

        # Statistics
        self.stats = {
            'readings_collected': 0,
            'readings_transmitted': 0,
            'transmission_failures': 0,
            'buffer_usage_percent': 0
        }

        # Threading
        self.transmission_thread = None
        self.heartbeat_thread = None
        self.lock = threading.Lock()

        logger.info(f"Sensor Gateway Node initialized: {node_id}")
        logger.info(f"Gateway target: {gateway_host}:{gateway_port}")

    def start(self, sensor_interval: float = 5.0, transmit_interval: float = 5.0):
        if self.is_running:
            logger.warning("Gateway already running")
            return

        logger.info("Starting Sensor Gateway Node...")

        # Start sensor reading
        self.sensor_driver.start_reading(interval_seconds=sensor_interval)

        # Connect CoAP client
        self.coap_client.connect()

        # Start transmission thread
        self.is_running = True
        self.transmission_thread = threading.Thread(
            target=self._transmission_loop,
            args=(transmit_interval,),
            daemon=True,
        )
        self.transmission_thread.start()

        # Start heartbeat thread
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
        )
        self.heartbeat_thread.start()

        logger.info("Sensor Gateway Node started")

    def stop(self):
        logger.info("Stopping Sensor Gateway Node...")
        self.is_running = False
        self.sensor_driver.stop_reading()
        self.coap_client.disconnect()

        if self.transmission_thread:
            self.transmission_thread.join(timeout=5.0)
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=5.0)

        logger.info("Sensor Gateway Node stopped")

    def _transmission_loop(self, interval: float):
        """Main transmission loop - send buffered data to Forensic Guardian."""
        connection_retry_count = 0
        max_retries = 3

        while self.is_running:
            try:
                # Ensure connection to gateway
                if not self.is_connected_to_gateway:
                    if self._connect_to_gateway():
                        connection_retry_count = 0
                        logger.info(f"Connected to Forensic Guardian at {self.gateway_host}")
                    else:
                        connection_retry_count += 1
                        if connection_retry_count >= max_retries:
                            logger.warning("Failed to connect to gateway after retries")
                            connection_retry_count = 0
                        time.sleep(interval)
                        continue

                # Get latest readings
                readings = self.sensor_driver.get_latest_readings()

                if readings:
                    # Transmit to gateway
                    success = self._transmit_to_gateway(readings)

                    with self.lock:
                        self.stats['readings_collected'] += len(readings)
                        if success:
                            self.stats['readings_transmitted'] += len(readings)
                            self.last_transmission_time = datetime.now()
                        else:
                            self.stats['transmission_failures'] += 1

                # Update buffer stats
                buffer_stats = self.sensor_driver.get_buffer_stats()
                with self.lock:
                    self.stats['buffer_usage_percent'] = min(
                        100,
                        int((buffer_stats['readings_count'] / 
                             buffer_stats['buffer_capacity']) * 100)
                    )

            except Exception as e:
                logger.error(f"Error in transmission loop: {e}")
                self.is_connected_to_gateway = False
                with self.lock:
                    self.stats['transmission_failures'] += 1

            time.sleep(interval)

    def _connect_to_gateway(self) -> bool:
        """Connect to Forensic Guardian via CoAP."""
        try:
            logger.debug(f"Connecting to gateway {self.gateway_host}:{self.gateway_port}")
            self.coap_client.connect()
            self.is_connected_to_gateway = self.coap_client.connected
            return self.is_connected_to_gateway
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.is_connected_to_gateway = False
            return False

    def _transmit_to_gateway(self, readings: list) -> bool:
        """Transmit sensor readings to Forensic Guardian via CoAP."""
        try:
            if not self.is_connected_to_gateway:
                return False

            readings_data = [r.to_dict() for r in readings]
            success = self.coap_client.send_readings(readings_data)

            if success:
                logger.debug(f"Transmitted {len(readings)} readings to gateway")
            else:
                logger.warning("CoAP send_readings returned failure")
                self.is_connected_to_gateway = False

            return success

        except Exception as e:
            logger.error(f"Transmission failed: {e}")
            self.is_connected_to_gateway = False
            return False

    def _heartbeat_loop(self):
        """Send periodic heartbeat to Forensic Guardian."""
        while self.is_running:
            try:
                self.coap_client.send_heartbeat()
            except Exception as e:
                logger.debug(f"Heartbeat send error: {e}")
            time.sleep(30.0)

    def get_status(self) -> Dict:
        """Get current node status."""
        with self.lock:
            buffer_stats = self.sensor_driver.get_buffer_stats()
            status = {
                'node_id': self.node_id,
                'running': self.is_running,
                'connected_to_gateway': self.is_connected_to_gateway,
                'last_transmission': self.last_transmission_time.isoformat() 
                                    if self.last_transmission_time else None,
                'buffer_readings': buffer_stats['readings_count'],
                'buffer_capacity': buffer_stats['buffer_capacity'],
                'buffer_full_hours': buffer_stats['buffer_full_hours'],
                'stats': self.stats.copy()
            }
        return status

    def get_recent_readings(self, count: int = 10):
        """Get recent sensor readings from buffer."""
        return self.sensor_driver.get_buffer_data(time_minutes=None)[:count]

    def get_buffer_info(self) -> Dict:
        """Get detailed buffer information."""
        return self.sensor_driver.get_buffer_stats()
