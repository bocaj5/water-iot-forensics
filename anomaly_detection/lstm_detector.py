"""LSTM autoencoder for temporal anomaly detection."""

import json
import numpy as np
import logging
from typing import Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class LSTMDetector:
    """LSTM autoencoder using TensorFlow Lite for reconstruction-error anomaly detection.

    Normalisation parameters (mean, std) are loaded from a JSON sidecar next
    to the .tflite file so that inference-time normalisation matches the
    global normalisation used during training. If the sidecar is missing we
    fall back to window-local normalisation (less accurate; see thesis
    § 6.5.3).
    """

    def __init__(self, model_file: Optional[str] = None):
        self.model_file = model_file
        self.model = None
        self.norm_mean: Optional[float] = None
        self.norm_std: Optional[float] = None
        self.per_sensor_norm: dict = {}  # sensor_type -> (mean, std)
        self.seq_len: Optional[int] = None
        self.score_scale: float = 10.0  # legacy default, overridden by
                                        # calibration in _calibrate if
                                        # normal-reference data is supplied
        self._load_model()
        self._load_norm_params()

    def _load_model(self):
        """Load pre-trained TensorFlow Lite model.

        Tries ai_edge_litert (the successor package to tflite-runtime, which
        is what Google now publishes for Python 3.12+), then tflite-runtime,
        then full TensorFlow as a fall-back. The first one that works wins.
        """
        if not (self.model_file and Path(self.model_file).exists()):
            logger.warning("LSTM model not loaded - will use fallback score")
            return

        # 1. ai_edge_litert (current Google-published runtime)
        try:
            from ai_edge_litert.interpreter import Interpreter as _Interp
            self.model = _Interp(model_path=self.model_file)
            self.model.allocate_tensors()
            logger.info(f"Loaded LSTM model via ai_edge_litert from {self.model_file}")
            return
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"ai_edge_litert load failed: {e}")

        # 2. legacy tflite_runtime
        try:
            import tflite_runtime.interpreter as tflite
            self.model = tflite.Interpreter(model_path=self.model_file)
            self.model.allocate_tensors()
            logger.info(f"Loaded LSTM model via tflite_runtime from {self.model_file}")
            return
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"tflite_runtime load failed: {e}")

        # 3. full TensorFlow
        try:
            import tensorflow as tf
            self.model = tf.lite.Interpreter(model_path=self.model_file)
            self.model.allocate_tensors()
            logger.info(f"Loaded LSTM model via tf.lite from {self.model_file}")
            return
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"tf.lite load failed: {e}")

        logger.warning("Neither ai_edge_litert, tflite_runtime, nor tensorflow available")

    def _load_norm_params(self):
        """Load training-time normalisation (mean, std, seq_len, per_sensor) from sidecar."""
        if not self.model_file:
            return
        sidecar = Path(self.model_file).with_suffix('.json')
        if not sidecar.exists():
            logger.warning(
                f"LSTM normalisation sidecar {sidecar} missing; "
                f"falling back to window-local z-score normalisation."
            )
            return
        try:
            with open(sidecar, 'r') as f:
                params = json.load(f)
            self.norm_mean = float(params.get('mean'))
            self.norm_std = float(params.get('std'))
            self.seq_len = int(params.get('seq_len', 50))
            per_sensor = params.get('per_sensor')
            if isinstance(per_sensor, dict):
                self.per_sensor_norm = {
                    k: (float(v['mean']), float(v['std']))
                    for k, v in per_sensor.items()
                }
            logger.info(
                f"Loaded LSTM normalisation: mean={self.norm_mean:.3f}, "
                f"std={self.norm_std:.3f}, seq_len={self.seq_len}, "
                f"per_sensor={list(self.per_sensor_norm.keys())}"
            )
        except Exception as e:
            logger.warning(f"Could not load LSTM sidecar: {e}")

    def predict(self, time_series: np.ndarray,
                sensor_type: Optional[str] = None) -> Tuple[float, float]:
        """Predict anomaly score from reconstruction error.

        Args:
            time_series: 1D array of recent sensor values
            sensor_type: optional sensor type (pH / Chlorine / Temperature)
                         used to look up per-sensor normalisation if the
                         training sidecar stored it.

        Returns:
            (score 0-1, confidence 0-1)
        """
        if self.model is None:
            return 0.3, 0.4

        try:
            # Prefer per-sensor global normalisation so training- and
            # inference-time input distributions agree; fall back to
            # the overall global mean/std and finally to window-local.
            mean_used, std_used = None, None
            if sensor_type and sensor_type in self.per_sensor_norm:
                mean_used, std_used = self.per_sensor_norm[sensor_type]
            elif self.norm_mean is not None and self.norm_std is not None:
                mean_used, std_used = self.norm_mean, self.norm_std

            if mean_used is not None and std_used is not None:
                normalized = (time_series - mean_used) / (std_used + 1e-6)
            else:
                mean = np.mean(time_series)
                std = np.std(time_series) + 1e-6
                normalized = (time_series - mean) / std

            input_details = self.model.get_input_details()
            output_details = self.model.get_output_details()

            expected_shape = input_details[0]['shape']
            seq_len = expected_shape[1] if len(expected_shape) > 1 else len(normalized)

            if len(normalized) > seq_len:
                normalized = normalized[-seq_len:]
            elif len(normalized) < seq_len:
                normalized = np.pad(normalized, (seq_len - len(normalized), 0))

            input_data = normalized.reshape(1, seq_len, 1).astype(np.float32)

            self.model.set_tensor(input_details[0]['index'], input_data)
            self.model.invoke()
            reconstructed = self.model.get_tensor(output_details[0]['index'])

            mse = float(np.mean((input_data - reconstructed) ** 2))
            score = min(mse * self.score_scale, 1.0)
            confidence = min(abs(mse) * 5, 1.0)

            return score, confidence
        except Exception as e:
            logger.warning(f"LSTM prediction error: {e}")
            return 0.3, 0.4
