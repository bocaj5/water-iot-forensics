"""Main anomaly detection engine combining SVM and LSTM in an ensemble."""

import logging
import numpy as np
from typing import Optional, Dict, Callable
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

from .feature_extractor import FeatureExtractor
from .svm_detector import SVMDetector
from .lstm_detector import LSTMDetector

logger = logging.getLogger(__name__)


@dataclass
class AnomalyResult:
    """Result from the anomaly detection engine."""
    timestamp: str
    sensor_type: str
    svm_score: float
    lstm_score: float
    ensemble_score: float
    is_anomaly: bool
    anomaly_type: str
    confidence: float
    severity: str  # NORMAL, HIGH, CRITICAL

    def to_dict(self) -> Dict:
        return asdict(self)


class AnomalyDetectionEngine:
    """Ensemble anomaly detection engine: SVM (0.6) + LSTM (0.4)."""

    def __init__(self,
                 svm_model_file: Optional[str] = None,
                 lstm_model_file: Optional[str] = None,
                 feature_window: int = 50,
                 anomaly_threshold: float = 0.65,
                 svm_weight: float = 0.6,
                 lstm_weight: float = 0.4,
                 alert_cooldown_sec: int = 60):
        self.feature_extractor = FeatureExtractor(window_size=feature_window)
        self.svm_detector = SVMDetector(model_file=svm_model_file)
        self.lstm_detector = LSTMDetector(model_file=lstm_model_file)

        self.time_series_buffer: Dict[str, deque] = {}
        self.svm_weight = svm_weight
        self.lstm_weight = lstm_weight
        self.anomaly_threshold = anomaly_threshold
        self.alert_cooldown = timedelta(seconds=alert_cooldown_sec)
        self._last_alert_time: Dict[str, datetime] = {}

        self.anomaly_callback: Optional[Callable] = None

        self.stats = {
            'readings_processed': 0,
            'anomalies_detected': 0,
            'last_anomaly_time': None,
        }

        self.latest_result: Optional[AnomalyResult] = None

        logger.info(
            f"AnomalyDetectionEngine initialized "
            f"(SVM:{svm_weight}, LSTM:{lstm_weight}, threshold:{anomaly_threshold})"
        )

    def set_anomaly_callback(self, callback: Callable):
        """Set callback for when an anomaly is detected: callback(result, reading_dict)."""
        self.anomaly_callback = callback

    def process_reading(self, sensor_type: str, value: float,
                        reading_dict: Optional[Dict] = None) -> Optional[AnomalyResult]:
        """Process a single sensor reading through the ensemble.

        Args:
            sensor_type: e.g. 'pH', 'Chlorine', 'Temperature'
            value: the sensor value
            reading_dict: optional original reading dict for callbacks

        Returns:
            AnomalyResult if feature window is full, else None
        """
        self.stats['readings_processed'] += 1

        # Buffer for LSTM
        if sensor_type not in self.time_series_buffer:
            self.time_series_buffer[sensor_type] = deque(maxlen=100)
        self.time_series_buffer[sensor_type].append(value)

        # Extract features
        features = self.feature_extractor.add_reading(sensor_type, value)
        if features is None:
            return None

        # SVM prediction
        svm_score, svm_conf = self.svm_detector.predict(features)

        # LSTM prediction
        ts = np.array(list(self.time_series_buffer[sensor_type]))
        lstm_score, lstm_conf = self.lstm_detector.predict(ts, sensor_type=sensor_type)

        # Ensemble
        ensemble_score = (self.svm_weight * svm_score) + (self.lstm_weight * lstm_score)
        is_anomaly = ensemble_score > self.anomaly_threshold

        # Classify
        anomaly_type = 'normal'
        severity = 'NORMAL'
        if is_anomaly:
            anomaly_type = self._classify_anomaly(sensor_type, features)
            severity = self._classify_severity(ensemble_score)

        result = AnomalyResult(
            timestamp=datetime.now().isoformat(),
            sensor_type=sensor_type,
            svm_score=round(svm_score, 4),
            lstm_score=round(lstm_score, 4),
            ensemble_score=round(ensemble_score, 4),
            is_anomaly=is_anomaly,
            anomaly_type=anomaly_type,
            confidence=round(max(svm_conf, lstm_conf), 4),
            severity=severity,
        )

        if is_anomaly:
            self.stats['anomalies_detected'] += 1
            self.stats['last_anomaly_time'] = result.timestamp
            now = datetime.now()
            last = self._last_alert_time.get(sensor_type)
            if last is None or (now - last) >= self.alert_cooldown:
                self._last_alert_time[sensor_type] = now
                logger.warning(
                    f"ANOMALY DETECTED: {anomaly_type} on {sensor_type} "
                    f"(score={ensemble_score:.3f}, severity={severity})"
                )
                if self.anomaly_callback:
                    try:
                        self.anomaly_callback(result, reading_dict or {})
                    except Exception as e:
                        logger.error(f"Error in anomaly callback: {e}")

        # Always track latest result for dashboard gauge
        self.latest_result = result

        return result

    def _classify_anomaly(self, sensor_type: str,
                          features: Dict[str, float]) -> str:
        """Classify the type of anomaly from features and sensor type."""
        z_score = abs(features.get('z_score_current', 0))
        rate = abs(features.get('rate_of_change', 0))
        current = features.get('current_value', 0)

        if sensor_type == 'pH':
            if current < 5.5:
                return 'acid_injection'
            elif current > 9.0:
                return 'base_injection'
        elif sensor_type == 'Chlorine':
            if current > 3.0:
                return 'chlorine_overdose'
        elif sensor_type == 'Temperature':
            if current > 36.0:
                return 'temperature_spike'

        if z_score > 4 or rate > 3:
            return 'chemical_overdose'
        elif rate > 0.5:
            return 'sensor_drift'
        return 'unknown'

    @staticmethod
    def _classify_severity(score: float) -> str:
        """Map ensemble score to severity level."""
        if score >= 0.8:
            return 'CRITICAL'
        elif score >= 0.6:
            return 'HIGH'
        return 'NORMAL'

    def get_stats(self) -> Dict:
        return self.stats.copy()
