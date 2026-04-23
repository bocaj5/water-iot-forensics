#!/usr/bin/env python3
"""
Train SVM + LSTM models from the test data JSONs.

Usage:
    python -m ml.train_models [--data-dir "tests/test data"] [--output-dir ml/models]

Produces:
    ml/models/svm_model.pkl      - Trained SVM with scaler
    ml/models/lstm_autoencoder.tflite  - LSTM autoencoder (TF Lite)
"""

import json
import pickle
import argparse
import logging
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anomaly_detection.feature_extractor import FeatureExtractor


# ── Data loading ──────────────────────────────────────────────────────────────

def load_json_file(path: Path) -> list:
    with open(path, 'r') as f:
        return json.load(f)


def load_all_data(data_dir: Path) -> list:
    """Load and merge all JSON data files."""
    records = []
    files_to_load = [
        'baseline_30_days.json',
        'extended_baseline_90_days.json',
        'comprehensive_attack_scenarios.json',
        'acid_injection_10_attacks.json',
        'multi_parameter_5_attacks.json',
    ]
    for fname in files_to_load:
        fpath = data_dir / fname
        if fpath.exists():
            data = load_json_file(fpath)
            records.extend(data)
            logger.info(f"Loaded {len(data)} records from {fname}")
        else:
            logger.warning(f"Data file not found: {fpath}")
    logger.info(f"Total records loaded: {len(records)}")
    return records


# ── Feature extraction ────────────────────────────────────────────────────────

def _per_sensor_anomaly(raw_key: str, value: float, rec: dict) -> bool:
    """Return True if *this specific sensor's value* is anomalous in this record.

    We intentionally do NOT use the record-level `severity` field for the
    per-sensor label, because an acid-injection record has
    severity=CRITICAL across the whole record even though only pH is
    attacked; labelling that record's Chlorine reading as an anomaly
    teaches the model that normal Chlorine = anomaly, which breaks
    Chlorine/Temperature detection.

    Labelling rules (from attack-scenario ground truth):
       pH          → anomaly if ph < 6.0 or ph > 9.0
       Chlorine    → anomaly if chlorine > 3.0 or chlorine < 0.3
       Temperature → anomaly if temperature > 35.0 or temperature < 5.0
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    if raw_key == 'ph':
        return v < 6.0 or v > 9.0
    if raw_key == 'chlorine':
        return v > 3.0 or v < 0.3
    if raw_key == 'temperature':
        return v > 35.0 or v < 5.0
    return False


def extract_features_and_labels(records: list, window_size: int = 50):
    """Extract windowed features from records, returning X, y arrays.

    Per-sensor labels are derived from the current window's most recent
    value (and, as a fallback for borderline transitions, from the
    record-level severity). This avoids the cross-sensor
    contamination bug in which the Chlorine feature vector of an acid-
    injection record was labelled "anomaly" even though its Chlorine
    value was perfectly normal.
    """
    records.sort(key=lambda r: r.get('timestamp', ''))

    sensor_keys = {'ph': 'pH', 'chlorine': 'Chlorine', 'temperature': 'Temperature'}

    all_features = []
    all_labels = []
    per_sensor_counts = {k: [0, 0] for k in sensor_keys}  # [normal, anomaly]

    for raw_key, sensor_type in sensor_keys.items():
        extractor = FeatureExtractor(window_size=window_size)
        for rec in records:
            value = rec.get(raw_key)
            if value is None:
                continue
            features = extractor.add_reading(sensor_type, float(value))
            if features is not None:
                all_features.append(list(features.values()))
                label = 1 if _per_sensor_anomaly(raw_key, value, rec) else 0
                all_labels.append(label)
                per_sensor_counts[raw_key][label] += 1

    X = np.array(all_features, dtype=np.float64)
    y = np.array(all_labels, dtype=np.int32)
    logger.info(f"Feature matrix shape: {X.shape}, overall anomaly ratio: {y.mean():.4f}")
    for k, (n, a) in per_sensor_counts.items():
        tot = n + a
        logger.info(f"  {k:<12s}: normal={n}, anomaly={a}, anomaly_ratio={a/tot:.4f}")
    return X, y


# ── SVM Training ──────────────────────────────────────────────────────────────

def train_svm(X: np.ndarray, y: np.ndarray, output_path: Path):
    """Train an SVM with RBF kernel and save with scaler."""
    from sklearn.svm import SVC
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    svm = SVC(kernel='rbf', C=10.0, gamma='scale', class_weight='balanced')
    svm.fit(X_train_scaled, y_train)

    y_pred = svm.predict(X_test_scaled)
    report = classification_report(y_test, y_pred, target_names=['Normal', 'Anomaly'])
    logger.info(f"SVM Classification Report:\n{report}")

    feature_names = [
        'current_value', 'mean', 'std', 'min', 'max', 'range',
        'median', 'rate_of_change', 'acceleration', 'autocorr_lag1',
        'entropy', 'z_score_current', 'skewness'
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'wb') as f:
        pickle.dump({
            'model': svm,
            'scaler': scaler,
            'feature_names': feature_names,
        }, f)
    logger.info(f"SVM model saved to {output_path}")


# ── LSTM Training ─────────────────────────────────────────────────────────────

def train_lstm(records: list, output_path: Path, seq_len: int = 50, epochs: int = 20):
    """Train LSTM autoencoder and export to TF Lite.

    Each sensor type is normalised independently with its own (mean, std),
    then the normalised per-sensor sequences are concatenated for training.
    The per-sensor normalisation parameters are written to the sidecar JSON
    so that inference uses the matching normalisation per sensor type.
    """
    try:
        import tensorflow as tf
    except ImportError:
        logger.warning("TensorFlow not available - skipping LSTM training")
        return

    sensor_keys = {'ph': 'pH', 'chlorine': 'Chlorine', 'temperature': 'Temperature'}
    per_sensor_norm: dict = {}
    all_sequences = []

    for raw_key, sensor_type in sensor_keys.items():
        s_values = []
        for rec in sorted(records, key=lambda r: r.get('timestamp', '')):
            v = rec.get(raw_key)
            if v is not None:
                s_values.append(float(v))
        s_values = np.array(s_values, dtype=np.float32)
        if len(s_values) == 0:
            continue
        s_mean = float(s_values.mean())
        s_std = float(s_values.std() + 1e-6)
        per_sensor_norm[sensor_type] = {'mean': s_mean, 'std': s_std}
        s_norm = (s_values - s_mean) / s_std
        for i in range(len(s_norm) - seq_len):
            all_sequences.append(s_norm[i:i + seq_len])
        logger.info(
            f"  {sensor_type}: {len(s_values)} values, "
            f"mean={s_mean:.3f}, std={s_std:.3f}"
        )

    X = np.array(all_sequences).reshape(-1, seq_len, 1)
    logger.info(f"LSTM training sequences: {X.shape}")

    # Overall (back-compat) mean/std across all normalised values (~0 / ~1).
    mean = float(X.mean())
    std = float(X.std() + 1e-6)

    # Build autoencoder.
    # unroll=True replaces the LSTM while-loop with static unrolled ops, which
    # avoids the TF 2.16 MLIR "missing attribute 'value'" crash during TFLite
    # conversion of stateful LSTM while_body graphs.
    encoder_input = tf.keras.Input(shape=(seq_len, 1))
    x = tf.keras.layers.LSTM(32, return_sequences=False, unroll=True)(encoder_input)
    x = tf.keras.layers.RepeatVector(seq_len)(x)
    x = tf.keras.layers.LSTM(32, return_sequences=True, unroll=True)(x)
    decoder_output = tf.keras.layers.TimeDistributed(tf.keras.layers.Dense(1))(x)

    model = tf.keras.Model(encoder_input, decoder_output)
    model.compile(optimizer='adam', loss='mse')

    model.fit(X, X, epochs=epochs, batch_size=64, validation_split=0.1, verbose=1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Always save Keras format first as a safe backup
    keras_path = output_path.with_suffix('.keras')
    model.save(keras_path)
    logger.info(f"LSTM Keras model saved to {keras_path}")

    # Export to TFLite
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    tflite_model = converter.convert()
    with open(output_path, 'wb') as f:
        f.write(tflite_model)
    logger.info(f"LSTM TFLite model saved to {output_path}")

    # Save normalization params alongside (both overall and per-sensor).
    params_path = output_path.with_suffix('.json')
    with open(params_path, 'w') as f:
        json.dump({
            'mean': mean,
            'std': std,
            'seq_len': seq_len,
            'per_sensor': per_sensor_norm,
        }, f, indent=2)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Train ML models for anomaly detection')
    parser.add_argument('--data-dir', default='tests/test data',
                        help='Directory containing JSON training data')
    parser.add_argument('--output-dir', default='ml/models',
                        help='Directory to save trained models')
    parser.add_argument('--window-size', type=int, default=50,
                        help='Feature extraction window size')
    parser.add_argument('--skip-lstm', action='store_true',
                        help='Skip LSTM training (useful on Pi 2B with limited RAM)')
    parser.add_argument('--skip-svm', action='store_true',
                        help='Skip SVM training (use when SVM model already exists)')

    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)

    logger.info("Loading training data...")
    records = load_all_data(data_dir)
    if not records:
        logger.error("No training data found")
        return 1

    logger.info("Extracting features...")
    X, y = extract_features_and_labels(records, window_size=args.window_size)

    if not args.skip_svm:
        logger.info("Training SVM...")
        train_svm(X, y, output_dir / 'svm_model.pkl')
    else:
        logger.info("Skipping SVM training (--skip-svm)")

    if not args.skip_lstm:
        logger.info("Training LSTM autoencoder...")
        train_lstm(records, output_dir / 'lstm_autoencoder.tflite',
                   seq_len=args.window_size)
    else:
        logger.info("Skipping LSTM training (--skip-lstm)")

    logger.info("Training complete!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
