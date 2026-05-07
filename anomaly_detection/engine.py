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
                 anomaly_threshold: float = 0.80,
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
        self.latest_anomaly_result: Optional[AnomalyResult] = None

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

        # Rule-based safety net: SVM was trained on synthetic data and
        # under-fires on real-hardware events (e.g. a 25→50°C spike). If
        # a feature crosses a clear physical threshold, force an anomaly
        # and boost the ensemble score so severity reflects it.
        if not is_anomaly and self._rule_based_anomaly(sensor_type, features):
            is_anomaly = True
            ensemble_score = max(ensemble_score, 0.75)

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
            self.latest_anomaly_result = result
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

    @staticmethod
    def _rule_based_anomaly(sensor_type: str,
                            features: Dict[str, float]) -> bool:
        """Hard physical thresholds that always trigger an anomaly.

        Acts as a safety net for the ML ensemble, which is trained on
        synthetic data and can miss real-world events. Tuned to fire on
        clearly out-of-spec readings without flagging normal noise.
        """
        current = features.get('current_value', 0)
        rate = abs(features.get('rate_of_change', 0))
        z = abs(features.get('z_score_current', 0))

        if sensor_type == 'pH':
            # Drinking water: 6.5–8.5. Anything outside or shifting fast is suspect.
            # Lower bound aligned with the acid_injection classifier so a real
            # lemon squeeze (drops pH 1–2 to ~5) fires; probe noise around 6 doesn't.
            if current < 5.5 or current > 8.5:
                return True
            if rate > 0.6 or z > 3.0:  # lemon juice / sudden chemistry change
                return True

        elif sensor_type == 'Temperature':
            # Hot/cold contamination — well below scald (50°C) but well above
            # the ambient room baseline we calibrated on (~22–25°C). Hot kettle
            # pour adds ~20°C → 42°C; ambient warming should not fire.
            if current > 35.0 or current < 5.0:
                return True
            if rate > 3.5 or z > 3.5:
                return True

        elif sensor_type == 'Chlorine':
            # WHO recommends 0.2–1.0 mg/L residual; ≥3.0 is overdose.
            if current > 3.0 or current < 0.15:
                return True
            if rate > 0.5 or z > 3.0:
                return True

        return False

    def _classify_anomaly(self, sensor_type: str,
                          features: Dict[str, float]) -> str:
        """Classify the type of anomaly from features and sensor type."""
        z_score_signed = features.get('z_score_current', 0)
        z_score = abs(z_score_signed)
        rate_signed = features.get('rate_of_change', 0)
        rate = abs(rate_signed)
        current = features.get('current_value', 0)
        mean = features.get('mean', current)

        if sensor_type == 'pH':
            if current < 5.5:
                return 'acid_injection'
            if current > 9.0:
                return 'base_injection'
            if rate > 1.0 or z_score > 3.5:
                return 'ph_drift'
            return 'ph_anomaly'

        if sensor_type == 'Chlorine':
            if current > 3.0:
                return 'chlorine_overdose'
            if current < 0.2:
                return 'chlorine_underdose'
            if rate > 0.5 or z_score > 3:
                return 'chlorine_drift'
            return 'chlorine_anomaly'

        if sensor_type == 'Temperature':
            # Hot-water introduction: absolute high OR rapid upward swing
            # away from the recent baseline. Catches both kettle-hot water
            # (>36°C) and warmer-than-ambient water (sustained rise).
            if current > 30.0 or rate_signed > 3.0 or (current > mean + 5 and z_score > 2):
                return 'temperature_spike'
            if current < 5.0 or rate_signed < -3.0:
                return 'temperature_drop'
            if rate > 2.5 or z_score > 3.5:
                return 'temperature_drift'
            return 'temperature_anomaly'

        # Unknown sensor type — keep a generic but informative label
        if z_score > 4 or rate > 3:
            return f'{sensor_type.lower()}_spike'
        if rate > 0.5:
            return f'{sensor_type.lower()}_drift'
        return f'{sensor_type.lower()}_anomaly'

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
