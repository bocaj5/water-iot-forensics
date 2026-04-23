#!/usr/bin/env python3
"""
Attack scenario test runner.

Runs all five attack scenarios through the ML anomaly detection engine,
measures detection latency and accuracy, then writes a JSON results report.

Usage:
    python -m tests.run_attack_tests [--svm ml/models/svm_model.pkl]
                                     [--lstm ml/models/lstm_autoencoder.tflite]
                                     [--output tests/results/attack_test_results.json]
                                     [--readings-per-scenario 300]

Output metrics per scenario and overall:
    - True Positives / False Negatives / True Negatives / False Positives
    - Precision, Recall, F1, Accuracy
    - Detection latency (ms from first attack reading to first anomaly flag)
    - Ensemble scores (SVM, LSTM, combined)
"""

import sys
import json
import time
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Allow running as script from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.attack_scenarios import SCENARIOS
from anomaly_detection.engine import AnomalyDetectionEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('AttackTestRunner')


# ── Normal baseline generator ─────────────────────────────────────────────────

def generate_normal_readings(count: int = 300) -> List[Dict]:
    """Generate normal operating readings to seed the feature window."""
    import random
    readings = []
    for _ in range(count):
        readings.append({'sensor_type': 'pH',          'value': round(7.2 + random.gauss(0, 0.1), 2), 'anomaly': None})
        readings.append({'sensor_type': 'Chlorine',    'value': round(2.1 + random.gauss(0, 0.1), 2), 'anomaly': None})
        readings.append({'sensor_type': 'Temperature', 'value': round(21.5 + random.gauss(0, 0.3), 1), 'anomaly': None})
    return readings


# ── Single scenario runner ────────────────────────────────────────────────────

def run_scenario(
    engine: AnomalyDetectionEngine,
    scenario_name: str,
    readings_per_scenario: int = 300,
    sim_seconds_per_reading: float = 1.0,
) -> Dict:
    """Run one attack scenario and return detailed metrics.

    Scenarios are driven with a simulated clock so the full attack trajectory
    is covered regardless of wall-clock timing. Each reading advances the
    virtual time by `sim_seconds_per_reading` seconds (default 1 s). A full
    300-reading run therefore covers the full 300-second scenario.
    """
    scenario = SCENARIOS[scenario_name]()
    logger.info(f"Running scenario: {scenario.name}")

    # Seed the engine with normal data first (fills feature window)
    normal_seed = generate_normal_readings(60)
    for r in normal_seed:
        engine.process_reading(r['sensor_type'], r['value'])

    results = []
    attack_start_sim: Optional[float] = None
    first_detection_sim: Optional[float] = None
    first_detection_wall_ms: Optional[float] = None
    attack_start_wall: Optional[float] = None

    # Feed attack readings one at a time, driven by simulated time
    readings_generated = 0
    iterations = 0
    sim_elapsed = 0.0
    # Cap iterations (not raw readings) so multi-reading scenarios cover the
    # full simulated duration just like single-reading scenarios.
    while scenario.is_active(sim_elapsed) and iterations < readings_per_scenario:
        iterations += 1
        batch = scenario.get_readings(sim_elapsed)
        for r in batch:
            is_attack_reading = r.get('anomaly') is not None
            if is_attack_reading and attack_start_sim is None:
                attack_start_sim = sim_elapsed
                attack_start_wall = time.monotonic()

            t_start = time.monotonic()
            result = engine.process_reading(r['sensor_type'], r['value'])
            inference_ms = (time.monotonic() - t_start) * 1000

            if result:
                detected = result.is_anomaly
                if detected and is_attack_reading and first_detection_sim is None:
                    first_detection_sim = sim_elapsed
                    first_detection_wall_ms = (time.monotonic() - attack_start_wall) * 1000

                results.append({
                    'sensor_type': r['sensor_type'],
                    'value': r['value'],
                    'sim_elapsed_sec': round(sim_elapsed, 2),
                    'is_attack_reading': is_attack_reading,
                    'detected': detected,
                    'svm_score': result.svm_score,
                    'lstm_score': result.lstm_score,
                    'ensemble_score': result.ensemble_score,
                    'inference_ms': round(inference_ms, 2),
                    'severity': result.severity,
                    'anomaly_type': result.anomaly_type,
                })
            readings_generated += 1
        sim_elapsed += sim_seconds_per_reading

    # Compute confusion matrix
    tp = sum(1 for r in results if r['is_attack_reading'] and r['detected'])
    fn = sum(1 for r in results if r['is_attack_reading'] and not r['detected'])
    fp = sum(1 for r in results if not r['is_attack_reading'] and r['detected'])
    tn = sum(1 for r in results if not r['is_attack_reading'] and not r['detected'])

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy  = (tp + tn) / len(results) if results else 0.0

    # Simulated-time detection latency: how many simulated seconds elapsed
    # between the first attack-labelled reading and the first detection.
    detection_latency_sim_sec = (
        (first_detection_sim - attack_start_sim)
        if (first_detection_sim is not None and attack_start_sim is not None)
        else None
    )
    # Wall-clock latency: actual inference latency from attack start to detect.
    detection_latency_ms = first_detection_wall_ms

    # Score distribution for attack readings
    attack_scores = [r['ensemble_score'] for r in results if r['is_attack_reading']]
    normal_scores = [r['ensemble_score'] for r in results if not r['is_attack_reading']]

    summary = {
        'scenario': scenario.name,
        'scenario_key': scenario_name,
        'description': scenario.description,
        'total_readings_evaluated': len(results),
        'attack_readings': tp + fn,
        'normal_readings': fp + tn,
        'confusion_matrix': {'TP': tp, 'FP': fp, 'TN': tn, 'FN': fn},
        'metrics': {
            'precision': round(precision, 4),
            'recall': round(recall, 4),
            'f1_score': round(f1, 4),
            'accuracy': round(accuracy, 4),
        },
        'detection_latency_ms': round(detection_latency_ms, 1) if detection_latency_ms else None,
        'detection_latency_sim_sec': round(detection_latency_sim_sec, 2) if detection_latency_sim_sec is not None else None,
        'avg_inference_ms': round(sum(r['inference_ms'] for r in results) / len(results), 2) if results else None,
        'scores': {
            'attack_readings': {
                'mean': round(sum(attack_scores) / len(attack_scores), 4) if attack_scores else None,
                'min': round(min(attack_scores), 4) if attack_scores else None,
                'max': round(max(attack_scores), 4) if attack_scores else None,
            },
            'normal_readings': {
                'mean': round(sum(normal_scores) / len(normal_scores), 4) if normal_scores else None,
                'min': round(min(normal_scores), 4) if normal_scores else None,
                'max': round(max(normal_scores), 4) if normal_scores else None,
            },
        },
    }

    if detection_latency_ms is not None:
        logger.info(
            f"  {scenario.name}: P={precision:.3f} R={recall:.3f} "
            f"F1={f1:.3f} WallLat={detection_latency_ms:.1f}ms "
            f"SimLat={detection_latency_sim_sec:.1f}s"
        )
    else:
        logger.info(
            f"  {scenario.name}: P={precision:.3f} R={recall:.3f} F1={f1:.3f} (no detection)"
        )
    return summary


# ── Overall aggregation ───────────────────────────────────────────────────────

def aggregate_results(scenario_results: List[Dict]) -> Dict:
    """Compute macro-averaged metrics across all scenarios."""
    metrics = [s['metrics'] for s in scenario_results]
    latencies = [s['detection_latency_ms'] for s in scenario_results if s['detection_latency_ms']]

    macro_precision = sum(m['precision'] for m in metrics) / len(metrics)
    macro_recall    = sum(m['recall']    for m in metrics) / len(metrics)
    macro_f1        = sum(m['f1_score']  for m in metrics) / len(metrics)
    macro_accuracy  = sum(m['accuracy']  for m in metrics) / len(metrics)

    total_tp = sum(s['confusion_matrix']['TP'] for s in scenario_results)
    total_fp = sum(s['confusion_matrix']['FP'] for s in scenario_results)
    total_tn = sum(s['confusion_matrix']['TN'] for s in scenario_results)
    total_fn = sum(s['confusion_matrix']['FN'] for s in scenario_results)

    return {
        'macro_precision': round(macro_precision, 4),
        'macro_recall': round(macro_recall, 4),
        'macro_f1': round(macro_f1, 4),
        'macro_accuracy': round(macro_accuracy, 4),
        'aggregate_confusion_matrix': {'TP': total_tp, 'FP': total_fp, 'TN': total_tn, 'FN': total_fn},
        'avg_detection_latency_ms': round(sum(latencies) / len(latencies), 1) if latencies else None,
        'scenarios_with_detection': len(latencies),
        'total_scenarios': len(scenario_results),
        'meets_95pct_accuracy': macro_accuracy >= 0.95,
        'meets_50ms_latency': (sum(latencies) / len(latencies) < 50) if latencies else False,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Run all 5 attack scenarios through ML engine')
    parser.add_argument('--svm',  default='ml/models/svm_model.pkl',
                        help='Path to SVM model .pkl')
    parser.add_argument('--lstm', default='ml/models/lstm_autoencoder.tflite',
                        help='Path to LSTM .tflite model')
    parser.add_argument('--output', default='tests/results/attack_test_results.json',
                        help='Output path for JSON results report')
    parser.add_argument('--readings-per-scenario', type=int, default=300,
                        help='Max readings to generate per scenario (default: 300)')
    args = parser.parse_args()

    svm_path  = args.svm  if Path(args.svm).exists()  else None
    lstm_path = args.lstm if Path(args.lstm).exists() else None

    if not svm_path:
        logger.warning(f"SVM model not found at {args.svm} — using fallback scoring")
    if not lstm_path:
        logger.warning(f"LSTM model not found at {args.lstm} — using fallback score 0.3")

    engine = AnomalyDetectionEngine(
        svm_model_file=svm_path,
        lstm_model_file=lstm_path,
        feature_window=50,
        anomaly_threshold=0.5,
    )

    scenario_results = []
    for name in SCENARIOS:
        # Fresh engine per scenario so window state doesn't bleed
        eng = AnomalyDetectionEngine(
            svm_model_file=svm_path,
            lstm_model_file=lstm_path,
            feature_window=50,
            anomaly_threshold=0.5,
        )
        result = run_scenario(eng, name, args.readings_per_scenario)
        scenario_results.append(result)

    overall = aggregate_results(scenario_results)

    report = {
        'test_run_timestamp': datetime.utcnow().isoformat(),
        'models_used': {
            'svm': svm_path or 'fallback',
            'lstm': lstm_path or 'fallback (score=0.3)',
        },
        'overall': overall,
        'scenarios': scenario_results,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    # Print summary table
    print("\n" + "=" * 70)
    print("ATTACK SCENARIO TEST RESULTS")
    print("=" * 70)
    print(f"{'Scenario':<28} {'Precision':>9} {'Recall':>8} {'F1':>6} {'Latency':>10}")
    print("-" * 70)
    for s in scenario_results:
        m = s['metrics']
        lat = f"{s['detection_latency_ms']:.0f}ms" if s['detection_latency_ms'] else "no detect"
        print(f"{s['scenario']:<28} {m['precision']:>9.3f} {m['recall']:>8.3f} {m['f1_score']:>6.3f} {lat:>10}")
    print("-" * 70)
    o = overall
    print(f"{'OVERALL (macro avg)':<28} {o['macro_precision']:>9.3f} {o['macro_recall']:>8.3f} {o['macro_f1']:>6.3f}")
    print(f"\nAccuracy: {o['macro_accuracy']:.1%}  |  Meets 95% target: {'YES' if o['meets_95pct_accuracy'] else 'NO'}")
    if o['avg_detection_latency_ms']:
        print(f"Avg latency: {o['avg_detection_latency_ms']:.1f}ms  |  Meets <50ms target: {'YES' if o['meets_50ms_latency'] else 'NO'}")
    print(f"\nFull results saved to: {output_path}")
    print("=" * 70)

    return 0


if __name__ == '__main__':
    sys.exit(main())
