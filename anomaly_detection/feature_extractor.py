"""Feature extraction from sensor readings for ML models."""

import numpy as np
from typing import Optional, Dict
from collections import deque

import logging

logger = logging.getLogger(__name__)


class FeatureExtractor:
    """Extract 13 statistical features from sliding windows of sensor readings."""

    def __init__(self, window_size: int = 50):
        self.window_size = window_size
        self.readings_buffer: Dict[str, deque] = {}

    def add_reading(self, sensor_type: str, value: float) -> Optional[Dict[str, float]]:
        """Add a reading value and return features when window is full."""
        if sensor_type not in self.readings_buffer:
            self.readings_buffer[sensor_type] = deque(maxlen=self.window_size)

        self.readings_buffer[sensor_type].append(value)

        if len(self.readings_buffer[sensor_type]) == self.window_size:
            return self._extract_features(sensor_type)
        return None

    def _extract_features(self, sensor_type: str) -> Dict[str, float]:
        """Extract 13 statistical features from the sensor buffer."""
        values = np.array(list(self.readings_buffer[sensor_type]))

        features = {
            'current_value': float(values[-1]),
            'mean': float(np.mean(values)),
            'std': float(np.std(values)),
            'min': float(np.min(values)),
            'max': float(np.max(values)),
            'range': float(np.max(values) - np.min(values)),
            'median': float(np.median(values)),
            'rate_of_change': float(values[-1] - values[-5]) if len(values) >= 5 else 0.0,
            'acceleration': float(
                (values[-1] - values[-2]) - (values[-2] - values[-3])
            ) if len(values) >= 3 else 0.0,
            'autocorr_lag1': float(
                np.corrcoef(values[:-1], values[1:])[0, 1]
            ) if len(values) > 1 and np.std(values) > 1e-10 else 0.0,
            'entropy': float(self._compute_entropy(values)),
            'z_score_current': float(
                (values[-1] - np.mean(values)) / (np.std(values) + 1e-6)
            ),
            'skewness': float(self._compute_skewness(values)),
        }

        return features

    @staticmethod
    def _compute_entropy(values: np.ndarray, bins: int = 10) -> float:
        """Compute Shannon entropy of values."""
        hist, _ = np.histogram(values, bins=bins)
        hist = hist[hist > 0]
        probabilities = hist / np.sum(hist)
        return float(-np.sum(probabilities * np.log2(probabilities + 1e-10)))

    @staticmethod
    def _compute_skewness(values: np.ndarray) -> float:
        """Compute skewness of values."""
        n = len(values)
        mean = np.mean(values)
        std = np.std(values) + 1e-6
        return float(np.sum(((values - mean) / std) ** 3) / n)

    def get_time_series(self, sensor_type: str) -> Optional[np.ndarray]:
        """Get the current time series buffer for a sensor type."""
        if sensor_type in self.readings_buffer and len(self.readings_buffer[sensor_type]) > 0:
            return np.array(list(self.readings_buffer[sensor_type]))
        return None

    def reset(self, sensor_type: str = None):
        """Reset feature extraction buffers."""
        if sensor_type:
            self.readings_buffer.pop(sensor_type, None)
        else:
            self.readings_buffer.clear()
