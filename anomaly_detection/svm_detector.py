"""SVM-based anomaly detector with RBF kernel."""

import numpy as np
import pickle
import logging
from typing import Optional, Tuple, Dict
from pathlib import Path

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    'current_value', 'mean', 'std', 'min', 'max', 'range',
    'median', 'rate_of_change', 'acceleration', 'autocorr_lag1',
    'entropy', 'z_score_current', 'skewness'
]


class SVMDetector:
    """Support Vector Machine for real-time anomaly detection."""

    def __init__(self, model_file: Optional[str] = None):
        self.model_file = model_file
        self.model = None
        self.scaler = None
        self.feature_names = FEATURE_NAMES
        self._load_model()

    def _load_model(self):
        """Load pre-trained model or log warning."""
        if self.model_file and Path(self.model_file).exists():
            try:
                with open(self.model_file, 'rb') as f:
                    data = pickle.load(f)
                self.model = data.get('model')
                self.scaler = data.get('scaler')
                stored_names = data.get('feature_names')
                if stored_names:
                    self.feature_names = stored_names
                logger.info(f"Loaded SVM model from {self.model_file}")
            except Exception as e:
                logger.warning(f"Could not load SVM model: {e}")
        else:
            logger.warning("SVM model not loaded - will use fallback detection")

    def predict(self, features: Dict[str, float]) -> Tuple[float, float]:
        """Predict anomaly score.

        Returns:
            (score 0-1, confidence 0-1)
        """
        if self.model is None or self.scaler is None:
            return self._fallback_detection(features)

        try:
            feature_vector = np.array(
                [features.get(name, 0.0) for name in self.feature_names]
            ).reshape(1, -1)

            feature_vector = np.nan_to_num(feature_vector, nan=0.0, posinf=1e6, neginf=-1e6)
            scaled_vector = self.scaler.transform(feature_vector)
            decision_score = self.model.decision_function(scaled_vector)[0]

            score = float(1 / (1 + np.exp(-decision_score)))
            confidence = float(abs(decision_score) / (abs(decision_score) + 1))

            return score, confidence
        except Exception as e:
            logger.warning(f"SVM prediction error: {e}")
            return self._fallback_detection(features)

    @staticmethod
    def _fallback_detection(features: Dict[str, float]) -> Tuple[float, float]:
        """Rule-based fallback when model is not available."""
        z_score = abs(features.get('z_score_current', 0))
        rate = abs(features.get('rate_of_change', 0))

        if z_score > 3 or rate > 2:
            return 0.8, 0.7
        elif z_score > 2 or rate > 1:
            return 0.5, 0.5
        else:
            return 0.2, 0.3
