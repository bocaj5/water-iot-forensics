"""
Five attack scenarios for testing forensic detection.

1. Acid Injection - Sudden pH drop (< 5.0)
2. Chlorine Overdose - Excessive chlorine (> 3.0 mg/L)
3. Temperature Spike - Rapid heating (> 35°C)
4. Multi-Parameter Attack - Coordinated acid + heat
5. Sequential Tampering - Gradual parameter shift
"""

import logging
from typing import List, Dict
from datetime import datetime
import random

logger = logging.getLogger(__name__)


class AttackScenario:
    """Base class for attack scenarios.

    Scenarios support two time modes:
      * Wall-clock (default): uses real elapsed time since construction.
      * Simulated: caller passes `elapsed_sec` directly; useful for offline
        benchmarking where readings must cover the full attack trajectory
        without waiting real minutes.
    """

    def __init__(self, name: str, description: str, duration_minutes: int = 5):
        self.name = name
        self.description = description
        self.duration_minutes = duration_minutes
        self.start_time = datetime.now()

    def _elapsed(self, elapsed_sec: 'float | None') -> float:
        if elapsed_sec is not None:
            return float(elapsed_sec)
        return (datetime.now() - self.start_time).total_seconds()

    def is_active(self, elapsed_sec: 'float | None' = None) -> bool:
        elapsed = self._elapsed(elapsed_sec) / 60
        return elapsed < self.duration_minutes

    def get_readings(self, elapsed_sec: 'float | None' = None) -> List[Dict]:
        raise NotImplementedError


class ScenarioAcidInjection(AttackScenario):
    """Acid Injection - pH drops from 7.2 to < 5.0"""

    def __init__(self):
        super().__init__(
            name="Acid Injection",
            description="Attacker injects acid, rapid pH drop below 5.0",
            duration_minutes=5
        )

    def get_readings(self, elapsed_sec: 'float | None' = None) -> List[Dict]:
        elapsed_sec = self._elapsed(elapsed_sec)

        if elapsed_sec < 60:
            value = 7.2 + random.gauss(0, 0.2)
        elif elapsed_sec < 180:
            drop = (elapsed_sec - 60) / 120
            value = 7.2 - (2.2 * drop) + random.gauss(0, 0.1)
        else:
            value = 5.0 + random.gauss(0, 0.2)

        value = max(0.0, min(14.0, value))
        return [{'sensor_type': 'pH', 'value': round(value, 2),
                 'anomaly': 'ACID_INJECTION' if value < 5.5 else None}]


class ScenarioChlorineOverdose(AttackScenario):
    """Chlorine Overdose - Spike to 5+ mg/L"""

    def __init__(self):
        super().__init__(
            name="Chlorine Overdose",
            description="Excessive chlorine pumped, spike to 5+ mg/L",
            duration_minutes=5
        )

    def get_readings(self, elapsed_sec: 'float | None' = None) -> List[Dict]:
        elapsed_sec = self._elapsed(elapsed_sec)

        if elapsed_sec < 90:
            value = 1.0 + random.gauss(0, 0.15)
        elif elapsed_sec < 180:
            spike = (elapsed_sec - 90) / 90
            value = 1.0 + (4.0 * spike) + random.gauss(0, 0.2)
        else:
            value = 5.0 + random.gauss(0, 0.3)

        value = max(0.0, min(5.0, value))
        return [{'sensor_type': 'Chlorine', 'value': round(value, 2),
                 'anomaly': 'CHLORINE_OVERDOSE' if value > 3.0 else None}]


class ScenarioTemperatureSpike(AttackScenario):
    """Temperature Spike - Rapid heating to > 40°C"""

    def __init__(self):
        super().__init__(
            name="Temperature Spike",
            description="Attacker heats water rapidly, temp > 40°C",
            duration_minutes=5
        )

    def get_readings(self, elapsed_sec: 'float | None' = None) -> List[Dict]:
        elapsed_sec = self._elapsed(elapsed_sec)

        if elapsed_sec < 60:
            value = 20.0 + random.gauss(0, 0.5)
        elif elapsed_sec < 180:
            heat = (elapsed_sec - 60) / 120
            value = 20.0 + (20.0 * heat) + random.gauss(0, 0.3)
        else:
            value = 40.0 + random.gauss(0, 0.5)

        value = max(-10.0, min(50.0, value))
        return [{'sensor_type': 'Temperature', 'value': round(value, 1),
                 'anomaly': 'TEMPERATURE_SPIKE' if value > 35.0 else None}]


class ScenarioMultiParameter(AttackScenario):
    """Multi-Parameter Attack - Acid + Heat simultaneously"""

    def __init__(self):
        super().__init__(
            name="Multi-Parameter Attack",
            description="Coordinated: acid injection + heating attack",
            duration_minutes=5
        )

    def get_readings(self, elapsed_sec: 'float | None' = None) -> List[Dict]:
        elapsed_sec = self._elapsed(elapsed_sec)
        readings = []

        if elapsed_sec < 60:
            ph_val = 7.2 + random.gauss(0, 0.2)
            temp_val = 20.0 + random.gauss(0, 0.5)
        elif elapsed_sec < 180:
            progress = (elapsed_sec - 60) / 120
            ph_val = 7.2 - (2.0 * progress)
            temp_val = 20.0 + (18.0 * progress)
        else:
            ph_val = 5.2 + random.gauss(0, 0.2)
            temp_val = 38.0 + random.gauss(0, 0.5)

        is_attack = ph_val < 5.5 and temp_val > 35.0
        readings.append({'sensor_type': 'pH', 'value': round(max(0, min(14, ph_val)), 2),
                        'anomaly': 'MULTI_PARAMETER' if is_attack else None})
        readings.append({'sensor_type': 'Temperature', 'value': round(max(-10, min(50, temp_val)), 1),
                        'anomaly': 'MULTI_PARAMETER' if is_attack else None})
        return readings


class ScenarioSequentialTampering(AttackScenario):
    """Sequential Tampering - Gradual parameter shifts"""

    def __init__(self):
        super().__init__(
            name="Sequential Tampering",
            description="Gradual modification: pH → Chlorine → Temperature",
            duration_minutes=5
        )

    def get_readings(self, elapsed_sec: 'float | None' = None) -> List[Dict]:
        elapsed_sec = self._elapsed(elapsed_sec)
        readings = []

        # Phase 1: pH tampering (0-100s)
        if elapsed_sec < 100:
            value = 7.0 if elapsed_sec < 60 else 7.0 - (1.5 * ((elapsed_sec - 60) / 40))
            readings.append({'sensor_type': 'pH', 'value': round(max(0, min(14, value)), 2),
                            'anomaly': 'SEQUENTIAL_PHASE_1' if value < 6.0 else None})

        # Phase 2: Chlorine tampering (100-200s)
        elif elapsed_sec < 200:
            value = 1.0 if elapsed_sec < 150 else 1.0 + (3.0 * ((elapsed_sec - 150) / 50))
            readings.append({'sensor_type': 'Chlorine', 'value': round(max(0, min(5, value)), 2),
                            'anomaly': 'SEQUENTIAL_PHASE_2' if value > 3.0 else None})

        # Phase 3: Temperature tampering (200-300s)
        else:
            value = 20.0 if elapsed_sec < 250 else 20.0 + (20.0 * ((elapsed_sec - 250) / 50))
            readings.append({'sensor_type': 'Temperature', 'value': round(max(-10, min(50, value)), 1),
                            'anomaly': 'SEQUENTIAL_PHASE_3' if value > 35.0 else None})

        return readings


SCENARIOS = {
    'acid_injection': ScenarioAcidInjection,
    'chlorine_overdose': ScenarioChlorineOverdose,
    'temperature_spike': ScenarioTemperatureSpike,
    'multi_parameter': ScenarioMultiParameter,
    'sequential_tampering': ScenarioSequentialTampering
}


def get_scenario(name: str) -> AttackScenario:
    if name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {name}")
    return SCENARIOS[name]()


def list_scenarios() -> List[Dict]:
    return [{'name': n, 'display': SCENARIOS[n]().name,
             'description': SCENARIOS[n]().description} for n in SCENARIOS]
