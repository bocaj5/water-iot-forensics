"""
GPIO sensor driver for Raspberry Pi 1 (Sensor Gateway node).
Reads from sensors connected via GPIO pins.
"""

import logging
import threading
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from collections import deque
import json

from .sensor_types import SensorReading, PHSensor, ChlorineSensor, TemperatureSensor

logger = logging.getLogger(__name__)


class GPIOSensorDriver:
    """Manages GPIO sensor reading on Sensor Gateway node."""

    def __init__(self, node_id: str = "pi1", buffer_hours: int = 12):
        """
        Initialize GPIO sensor driver.

        Args:
            node_id: Node identifier (typically 'pi1' for Sensor Gateway)
            buffer_hours: Hours of data to keep in local buffer
        """
        self.node_id = node_id
        self.buffer_hours = buffer_hours

        # Initialize sensors with GPIO pins
        self.ph_sensor = PHSensor(gpio_pin=4, node_id=node_id)
        self.chlorine_sensor = ChlorineSensor(gpio_pin=17, node_id=node_id)
        self.temperature_sensor = TemperatureSensor(gpio_pin=27, node_id=node_id)

        # Sensor list
        self.sensors = [
            self.ph_sensor,
            self.chlorine_sensor,
            self.temperature_sensor
        ]

        # Data buffer (circular, max 12 hours)
        self.reading_buffer = deque(maxlen=43200)  # 12 hours @ 1 reading/second
        self.buffer_start_time = datetime.now()

        # Threading
        self.reading_thread = None
        self.is_running = False
        self.lock = threading.Lock()

        logger.info(f"GPIO Sensor Driver initialized on {node_id}")
        logger.info(f"Sensors: pH (GPIO4), Chlorine (GPIO17), Temperature (GPIO27)")

    def start_reading(self, interval_seconds: float = 5.0):
        """
        Start continuous sensor reading thread.

        Args:
            interval_seconds: Reading interval in seconds
        """
        if self.is_running:
            logger.warning("Sensor reading already running")
            return

        self.is_running = True
        self.reading_thread = threading.Thread(
            target=self._reading_loop,
            args=(interval_seconds,),
            daemon=True
        )
        self.reading_thread.start()
        logger.info(f"Sensor reading started (interval: {interval_seconds}s)")

    def stop_reading(self):
        """Stop sensor reading thread."""
        self.is_running = False
        if self.reading_thread:
            self.reading_thread.join(timeout=5.0)
        logger.info("Sensor reading stopped")

    def _reading_loop(self, interval: float):
        """Main sensor reading loop."""
        while self.is_running:
            try:
                readings = self.read_all_sensors()
                with self.lock:
                    for reading in readings:
                        self.reading_buffer.append(reading)

                logger.debug(f"Read {len(readings)} sensor values")

            except Exception as e:
                logger.error(f"Error in reading loop: {e}")

            import time
            time.sleep(interval)

    def read_all_sensors(self) -> List[SensorReading]:
        """Read all sensors once."""
        readings = []
        for sensor in self.sensors:
            try:
                reading = sensor.read()
                readings.append(reading)
            except Exception as e:
                logger.error(f"Error reading {sensor.sensor_type}: {e}")

        return readings

    def get_latest_readings(self) -> List[SensorReading]:
        """Get latest reading from each sensor."""
        with self.lock:
            if not self.reading_buffer:
                return []

            # Group by sensor type, get latest
            latest = {}
            for reading in reversed(self.reading_buffer):
                if reading.sensor_type not in latest:
                    latest[reading.sensor_type] = reading

            return list(latest.values())

    def get_buffer_data(self, time_minutes: Optional[int] = None) -> List[Dict]:
        """
        Get buffered sensor data.

        Args:
            time_minutes: Get data from last N minutes (None = all)

        Returns:
            List of reading dictionaries
        """
        with self.lock:
            data = []
            cutoff_time = datetime.now() - timedelta(minutes=time_minutes) if time_minutes else None

            for reading in self.reading_buffer:
                if cutoff_time is None or reading.timestamp >= cutoff_time:
                    data.append(reading.to_dict())

            return data

    def get_buffer_stats(self) -> Dict:
        """Get statistics about buffer contents."""
        with self.lock:
            if not self.reading_buffer:
                return {
                    'readings_count': 0,
                    'buffer_full_hours': 0,
                    'oldest_reading': None,
                    'newest_reading': None,
                    'buffer_capacity': self.reading_buffer.maxlen,
                }

            readings_list = list(self.reading_buffer)
            oldest = readings_list[0]
            newest = readings_list[-1]
            duration = (newest.timestamp - oldest.timestamp).total_seconds() / 3600

            return {
                'readings_count': len(readings_list),
                'buffer_full_hours': round(duration, 2),
                'oldest_reading': oldest.timestamp.isoformat(),
                'newest_reading': newest.timestamp.isoformat(),
                'buffer_capacity': self.reading_buffer.maxlen
            }

    def clear_buffer(self):
        """Clear the reading buffer."""
        with self.lock:
            self.reading_buffer.clear()
            self.buffer_start_time = datetime.now()
        logger.info("Reading buffer cleared")
