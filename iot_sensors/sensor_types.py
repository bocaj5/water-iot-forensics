"""
Sensor type definitions and driver classes for water treatment IoT system.

Hardware supported:
  - pH:          Analog pH board (e.g. DFRobot SEN0161) via ADS1115 ADC over I2C
  - Temperature: DS18B20 1-Wire digital probe via kernel sysfs
  - Chlorine:    No physical sensor — always simulated

Each sensor attempts real hardware first and falls back to simulation
automatically if the hardware is unavailable (not wired, not detected,
needs reboot after DT overlay change, etc.).  confidence=1.0 for real
readings, 0.5 for simulated readings.

Hardware setup requirements (Pi B):
  /boot/firmware/config.txt must contain:
    dtoverlay=w1-gpio,gpiopin=4   # DS18B20 on GPIO4
    dtparam=i2c_arm=on            # ADS1115 on I2C1 (GPIO2/GPIO3)
  A reboot is required after adding these lines.
  smbus2 must be installed in the venv: pip install smbus2
"""

import glob
import logging
import random
import struct
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import json

logger = logging.getLogger(__name__)


# ── ADS1115 constants ──────────────────────────────────────────────────────
_ADS1115_ADDR        = 0x48   # ADDR pin to GND
_ADS1115_REG_CONV    = 0x00
_ADS1115_REG_CONFIG  = 0x01
# Config: OS=1 (begin single), MUX=100 (AIN0/GND), PGA=001 (±4.096V),
#         MODE=1 (single-shot), DR=100 (128SPS), COMP_MODE/POL/LAT/QUE=default
_ADS1115_CFG_HI      = 0xC3   # 1100_0011
_ADS1115_CFG_LO      = 0x83   # 1000_0011
_ADS1115_VFS         = 4.096  # Volts full-scale for PGA=001

# pH voltage-to-pH conversion for generic analog pH board at 3.3V supply.
#
# Calibration is board-specific. To calibrate accurately, dip the probe in
# pH 7.0 buffer solution and set _PH_MIDPOINT_V to the voltage you read.
# Then dip in pH 4.0 buffer and set _PH_SLOPE_V_PER_PH = (Vmid - V4) / 3.0
#
# Empirical midpoint measured 21 Apr 2026 in tap water (~pH 7):
# AIN0 = 1.3245 V → set as Vmid so tap water reads ≈ pH 7.
# Slope: standard Nernst 59.2mV/pH at 25°C ≈ 0.059 V/pH (unscaled electrode).
# Adjust after proper buffer calibration.
_PH_MIDPOINT_V       = 1.3245  # V — measured at pH 7 (update after calibration)
_PH_SLOPE_V_PER_PH   = 0.059   # V/pH — Nernst slope at 25°C, inverted board


@dataclass
class SensorReading:
    """Single sensor reading with metadata."""
    sensor_id: str
    sensor_type: str  # 'pH', 'Chlorine', 'Temperature'
    value: float
    unit: str
    timestamp: datetime
    node_id: str
    raw_value: Optional[float] = None
    confidence: float = 1.0  # 1.0 = real hardware, 0.5 = simulated

    def to_dict(self):
        return {
            'sensor_id': self.sensor_id,
            'sensor_type': self.sensor_type,
            'value': self.value,
            'unit': self.unit,
            'timestamp': self.timestamp.isoformat(),
            'node_id': self.node_id,
            'raw_value': self.raw_value,
            'confidence': self.confidence,
        }

    def to_json(self):
        return json.dumps(self.to_dict())

    @staticmethod
    def from_dict(data: dict):
        return SensorReading(
            sensor_id=data['sensor_id'],
            sensor_type=data['sensor_type'],
            value=data['value'],
            unit=data['unit'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            node_id=data['node_id'],
            raw_value=data.get('raw_value'),
            confidence=data.get('confidence', 1.0),
        )


# ══════════════════════════════════════════════════════════════════════════════
# pH sensor — ADS1115 on I2C
# ══════════════════════════════════════════════════════════════════════════════

class PHSensor:
    """
    pH sensor via an analog pH board (e.g. DFRobot SEN0161) connected to
    ADS1115 channel AIN0 over I2C.

    Falls back to simulation if the ADS1115 cannot be opened.
    """

    def __init__(self, gpio_pin: int, node_id: str,
                 i2c_bus: int = 1,
                 i2c_address: int = _ADS1115_ADDR,
                 calibration_points: dict = None):
        self.gpio_pin = gpio_pin
        self.node_id = node_id
        self.sensor_id = f"ph_ads1115_{i2c_address:#04x}"
        self.sensor_type = "pH"
        self.unit = "pH"
        self.min_value = 0.0
        self.max_value = 14.0
        self._i2c_bus = i2c_bus
        self._i2c_address = i2c_address
        self._bus = None
        self._hw_available = False
        self._hw_warned = False

        self.calibration_points = calibration_points or {
            'neutral': 7.0,
            'acidic': 6.0,
            'basic': 8.0,
        }

        self._init_hardware()

    def _init_hardware(self):
        try:
            import smbus2
            bus = smbus2.SMBus(self._i2c_bus)
            # Probe: write config and read back 2 bytes — raises OSError if absent
            bus.write_i2c_block_data(
                self._i2c_address, _ADS1115_REG_CONFIG,
                [_ADS1115_CFG_HI, _ADS1115_CFG_LO]
            )
            time.sleep(0.01)
            bus.read_i2c_block_data(self._i2c_address, _ADS1115_REG_CONV, 2)
            self._bus = bus
            self._hw_available = True
            logger.info(f"PHSensor: ADS1115 found on I2C{self._i2c_bus} @ {self._i2c_address:#04x}")
        except Exception as exc:
            logger.warning(f"PHSensor: ADS1115 not available ({exc}) — using simulation")

    def _read_ads1115_voltage(self) -> float:
        """Trigger single-shot conversion on AIN0 and return voltage."""
        import smbus2
        self._bus.write_i2c_block_data(
            self._i2c_address, _ADS1115_REG_CONFIG,
            [_ADS1115_CFG_HI, _ADS1115_CFG_LO]
        )
        time.sleep(0.009)  # 128 SPS → ~7.8ms per conversion
        raw_bytes = self._bus.read_i2c_block_data(
            self._i2c_address, _ADS1115_REG_CONV, 2
        )
        raw = struct.unpack('>h', bytes(raw_bytes))[0]  # signed 16-bit big-endian
        return (raw / 32767.0) * _ADS1115_VFS

    def _voltage_to_ph(self, voltage: float) -> float:
        return 7.0 + (_PH_MIDPOINT_V - voltage) / _PH_SLOPE_V_PER_PH

    def read(self) -> SensorReading:
        if self._hw_available:
            try:
                voltage = self._read_ads1115_voltage()
                value = self._voltage_to_ph(voltage)
                value = round(max(self.min_value, min(self.max_value, value)), 2)
                return SensorReading(
                    sensor_id=self.sensor_id,
                    sensor_type=self.sensor_type,
                    value=value,
                    unit=self.unit,
                    timestamp=datetime.now(),
                    node_id=self.node_id,
                    raw_value=round(voltage, 4),
                    confidence=1.0,
                )
            except Exception as exc:
                if not self._hw_warned:
                    logger.warning(f"PHSensor: hardware read failed ({exc}), falling back to simulation")
                    self._hw_warned = True
                self._hw_available = False

        # Simulation fallback — 0.2% spike rate, tighter normal std to match training data
        value = 7.0 + random.gauss(0, 0.15) if random.random() < 0.998 else 9.5 + random.gauss(0, 0.5)
        value = round(max(self.min_value, min(self.max_value, value)), 2)
        return SensorReading(
            sensor_id=self.sensor_id,
            sensor_type=self.sensor_type,
            value=value,
            unit=self.unit,
            timestamp=datetime.now(),
            node_id=self.node_id,
            raw_value=value,
            confidence=0.5,
        )

    @property
    def is_real(self) -> bool:
        return self._hw_available


# ══════════════════════════════════════════════════════════════════════════════
# Temperature sensor — DS18B20 via 1-Wire sysfs
# ══════════════════════════════════════════════════════════════════════════════

class TemperatureSensor:
    """
    DS18B20 1-Wire digital temperature probe.

    Reads from /sys/bus/w1/devices/28-*/temperature (millidegrees C).
    Falls back to simulation if no device is found.

    Requires in /boot/firmware/config.txt:
        dtoverlay=w1-gpio,gpiopin=4
    and a reboot.
    """

    def __init__(self, gpio_pin: int, node_id: str):
        self.gpio_pin = gpio_pin
        self.node_id = node_id
        self.sensor_type = "Temperature"
        self.unit = "°C"
        self.min_value = -10.0
        self.max_value = 50.0
        self._hw_warned = False

        self._sysfs_path = self._find_device()
        if self._sysfs_path:
            self.sensor_id = f"temp_ds18b20_{self._sysfs_path.split('/')[-2]}"
            logger.info(f"TemperatureSensor: DS18B20 found at {self._sysfs_path}")
        else:
            self.sensor_id = f"temp_sim_gpio{gpio_pin}"
            logger.warning("TemperatureSensor: DS18B20 not found — using simulation. "
                           "Ensure dtoverlay=w1-gpio,gpiopin=4 is in /boot/firmware/config.txt and reboot.")

    @staticmethod
    def _find_device() -> Optional[str]:
        matches = glob.glob('/sys/bus/w1/devices/28-*/temperature')
        return matches[0] if matches else None

    @property
    def is_real(self) -> bool:
        return self._sysfs_path is not None

    def read(self) -> SensorReading:
        if self._sysfs_path:
            try:
                with open(self._sysfs_path) as f:
                    millideg = int(f.read().strip())
                value = round(millideg / 1000.0, 1)
                value = max(self.min_value, min(self.max_value, value))
                return SensorReading(
                    sensor_id=self.sensor_id,
                    sensor_type=self.sensor_type,
                    value=value,
                    unit=self.unit,
                    timestamp=datetime.now(),
                    node_id=self.node_id,
                    raw_value=millideg,
                    confidence=1.0,
                )
            except Exception as exc:
                if not self._hw_warned:
                    logger.warning(f"TemperatureSensor: read failed ({exc}), falling back to simulation")
                    self._hw_warned = True
                self._sysfs_path = None  # stop trying

        # Simulation fallback — 0.1% spike rate
        value = 20.0 + random.gauss(0, 2.0) if random.random() < 0.999 else 36.0 + random.gauss(0, 1.0)
        value = round(max(self.min_value, min(self.max_value, value)), 1)
        return SensorReading(
            sensor_id=self.sensor_id,
            sensor_type=self.sensor_type,
            value=value,
            unit=self.unit,
            timestamp=datetime.now(),
            node_id=self.node_id,
            raw_value=value,
            confidence=0.5,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Chlorine sensor — simulation only (no physical sensor)
# ══════════════════════════════════════════════════════════════════════════════

class ChlorineSensor:
    """
    Chlorine residual sensor — simulated (no physical hardware).

    confidence is always 0.5 to indicate simulated data.
    Required for attack scenario injection which needs all three sensor types.
    """

    def __init__(self, gpio_pin: int, node_id: str):
        self.gpio_pin = gpio_pin
        self.node_id = node_id
        self.sensor_id = f"chlorine_sim_gpio{gpio_pin}"
        self.sensor_type = "Chlorine"
        self.unit = "mg/L"
        self.min_value = 0.0
        self.max_value = 5.0
        logger.info("ChlorineSensor: no physical sensor — using simulation (confidence=0.5)")

    @property
    def is_real(self) -> bool:
        return False

    def read(self) -> SensorReading:
        # 0.2% spike rate
        value = 1.0 + random.gauss(0, 0.15) if random.random() < 0.998 else 3.5 + random.gauss(0, 0.5)
        value = round(max(self.min_value, min(self.max_value, value)), 2)
        return SensorReading(
            sensor_id=self.sensor_id,
            sensor_type=self.sensor_type,
            value=value,
            unit=self.unit,
            timestamp=datetime.now(),
            node_id=self.node_id,
            raw_value=value,
            confidence=0.5,
        )
