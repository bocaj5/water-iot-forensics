"""
Unit tests for the anomaly detection engine, feature extractor,
forensic collector, chain of custody, and crypto manager.

Run:
    pytest tests/test_unit.py -v
    pytest tests/test_unit.py -v --cov=anomaly_detection --cov=forensics --cov=config --cov-report=term-missing
"""

import sys
import os
import json
import time
import hashlib
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ══════════════════════════════════════════════════════════════════════════════
# FeatureExtractor
# ══════════════════════════════════════════════════════════════════════════════

class TestFeatureExtractor:
    from anomaly_detection.feature_extractor import FeatureExtractor

    def setup_method(self):
        from anomaly_detection.feature_extractor import FeatureExtractor
        self.fe = FeatureExtractor(window_size=10)

    def test_returns_none_until_window_full(self):
        for i in range(9):
            result = self.fe.add_reading('pH', 7.0 + i * 0.01)
            assert result is None

    def test_returns_features_when_window_full(self):
        for i in range(10):
            result = self.fe.add_reading('pH', 7.0 + i * 0.01)
        assert result is not None
        assert isinstance(result, dict)

    def test_feature_keys_present(self):
        for i in range(10):
            result = self.fe.add_reading('pH', 7.0)
        expected_keys = [
            'current_value', 'mean', 'std', 'min', 'max', 'range',
            'median', 'rate_of_change', 'acceleration', 'autocorr_lag1',
            'entropy', 'z_score_current', 'skewness',
        ]
        assert all(k in result for k in expected_keys)

    def test_feature_count(self):
        for i in range(10):
            result = self.fe.add_reading('Chlorine', 2.0)
        assert len(result) == 13

    def test_multiple_sensor_types_independent(self):
        for i in range(10):
            self.fe.add_reading('pH', 7.0)
        for i in range(5):
            result = self.fe.add_reading('Chlorine', 2.0)
            assert result is None  # Chlorine window not yet full

    def test_constant_signal_std_zero(self):
        for i in range(10):
            result = self.fe.add_reading('Temperature', 20.0)
        assert result['std'] == pytest.approx(0.0, abs=1e-6)
        assert result['range'] == pytest.approx(0.0, abs=1e-6)

    def test_anomalous_spike_z_score(self):
        for i in range(9):
            self.fe.add_reading('pH', 7.0)
        result = self.fe.add_reading('pH', 12.0)  # spike
        assert result['z_score_current'] > 2.0

    def test_get_time_series(self):
        for i in range(5):
            self.fe.add_reading('pH', 7.0)
        ts = self.fe.get_time_series('pH')
        assert ts is not None
        assert len(ts) == 5

    def test_reset_clears_buffer(self):
        for i in range(10):
            self.fe.add_reading('pH', 7.0)
        self.fe.reset('pH')
        result = self.fe.add_reading('pH', 7.0)
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# SVMDetector
# ══════════════════════════════════════════════════════════════════════════════

class TestSVMDetector:

    def test_fallback_without_model(self):
        from anomaly_detection.svm_detector import SVMDetector
        det = SVMDetector(model_file=None)
        features = {k: 0.0 for k in [
            'current_value', 'mean', 'std', 'min', 'max', 'range',
            'median', 'rate_of_change', 'acceleration', 'autocorr_lag1',
            'entropy', 'z_score_current', 'skewness',
        ]}
        score, conf = det.predict(features)
        assert 0.0 <= score <= 1.0
        assert 0.0 <= conf <= 1.0

    def test_missing_model_file_graceful(self):
        from anomaly_detection.svm_detector import SVMDetector
        det = SVMDetector(model_file='/nonexistent/model.pkl')
        features = {'current_value': 7.0, 'mean': 7.0, 'std': 0.1,
                    'min': 6.9, 'max': 7.1, 'range': 0.2,
                    'median': 7.0, 'rate_of_change': 0.0, 'acceleration': 0.0,
                    'autocorr_lag1': 0.9, 'entropy': 2.5,
                    'z_score_current': 0.0, 'skewness': 0.0}
        score, conf = det.predict(features)  # should not raise
        assert isinstance(score, float)


# ══════════════════════════════════════════════════════════════════════════════
# LSTMDetector
# ══════════════════════════════════════════════════════════════════════════════

class TestLSTMDetector:

    def test_fallback_score_without_model(self):
        from anomaly_detection.lstm_detector import LSTMDetector
        import numpy as np
        det = LSTMDetector(model_file=None)
        ts = np.array([7.0] * 50)
        score, conf = det.predict(ts)
        assert score == pytest.approx(0.3)
        assert conf == pytest.approx(0.4)

    def test_fallback_score_with_missing_file(self):
        from anomaly_detection.lstm_detector import LSTMDetector
        import numpy as np
        det = LSTMDetector(model_file='/nonexistent.tflite')
        ts = np.array([7.0] * 50)
        score, conf = det.predict(ts)
        assert score == pytest.approx(0.3)


# ══════════════════════════════════════════════════════════════════════════════
# AnomalyDetectionEngine
# ══════════════════════════════════════════════════════════════════════════════

class TestAnomalyDetectionEngine:

    def setup_method(self):
        from anomaly_detection.engine import AnomalyDetectionEngine
        self.engine = AnomalyDetectionEngine(
            svm_model_file=None,
            lstm_model_file=None,
            feature_window=10,
            anomaly_threshold=0.5,
        )

    def test_returns_none_before_window_fills(self):
        for i in range(9):
            result = self.engine.process_reading('pH', 7.0)
            assert result is None

    def test_returns_result_after_window_fills(self):
        for i in range(10):
            result = self.engine.process_reading('pH', 7.0)
        assert result is not None

    def test_stats_readings_processed(self):
        for i in range(15):
            self.engine.process_reading('pH', 7.0)
        assert self.engine.stats['readings_processed'] == 15

    def test_anomaly_callback_triggered(self):
        callback_calls = []
        self.engine.set_anomaly_callback(lambda r, d: callback_calls.append(r))

        # Use a spiked value that forces high score through fallback
        with patch.object(self.engine.svm_detector, 'predict', return_value=(0.9, 0.9)):
            with patch.object(self.engine.lstm_detector, 'predict', return_value=(0.9, 0.9)):
                for i in range(10):
                    self.engine.process_reading('pH', 7.0)

        assert len(callback_calls) >= 1

    def test_latest_result_updated(self):
        assert self.engine.latest_result is None
        for i in range(10):
            self.engine.process_reading('pH', 7.0)
        assert self.engine.latest_result is not None

    def test_anomaly_result_fields(self):
        for i in range(10):
            result = self.engine.process_reading('pH', 7.0)
        assert hasattr(result, 'svm_score')
        assert hasattr(result, 'lstm_score')
        assert hasattr(result, 'ensemble_score')
        assert hasattr(result, 'is_anomaly')
        assert hasattr(result, 'severity')
        assert hasattr(result, 'anomaly_type')

    def test_ensemble_score_weighted(self):
        with patch.object(self.engine.svm_detector, 'predict', return_value=(0.8, 0.9)):
            with patch.object(self.engine.lstm_detector, 'predict', return_value=(0.4, 0.8)):
                for i in range(10):
                    result = self.engine.process_reading('pH', 7.0)
        # 0.6*0.8 + 0.4*0.4 = 0.48 + 0.16 = 0.64
        assert result.ensemble_score == pytest.approx(0.64, abs=0.01)

    def test_severity_levels(self):
        with patch.object(self.engine.svm_detector, 'predict', return_value=(0.95, 0.99)):
            with patch.object(self.engine.lstm_detector, 'predict', return_value=(0.95, 0.99)):
                for i in range(10):
                    result = self.engine.process_reading('pH', 12.0)
        assert result.severity in ('HIGH', 'CRITICAL')

    def test_get_stats(self):
        for i in range(10):
            self.engine.process_reading('pH', 7.0)
        stats = self.engine.get_stats()
        assert 'readings_processed' in stats
        assert 'anomalies_detected' in stats


# ══════════════════════════════════════════════════════════════════════════════
# ChainOfCustodyManager
# ══════════════════════════════════════════════════════════════════════════════

class TestChainOfCustodyManager:

    def setup_method(self):
        from forensics.chain_of_custody import ChainOfCustodyManager
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = ChainOfCustodyManager(evidence_dir=self.tmpdir)

    def test_log_action_creates_entry(self):
        entry = self.mgr.log_action('ev-001', 'collected', hash_value='abc123')
        assert entry.evidence_id == 'ev-001'
        assert entry.action == 'collected'

    def test_entry_persisted_to_jsonl(self):
        self.mgr.log_action('ev-001', 'collected', hash_value='abc123')
        log_path = Path(self.tmpdir) / 'chain_of_custody.jsonl'
        assert log_path.exists()
        with open(log_path) as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) == 1

    def test_multiple_entries_appended(self):
        for action in ['collected', 'transmitted', 'verified']:
            self.mgr.log_action('ev-001', action)
        log_path = Path(self.tmpdir) / 'chain_of_custody.jsonl'
        with open(log_path) as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) == 3

    def test_verify_chain_returns_dict(self):
        self.mgr.log_action('ev-002', 'collected', hash_value='xyz')
        result = self.mgr.verify_chain('ev-002')
        assert 'evidence_id' in result
        assert result['total_entries'] == 1

    def test_get_entries_for_evidence(self):
        self.mgr.log_action('ev-003', 'collected')
        self.mgr.log_action('ev-003', 'analyzed')
        entries = self.mgr.get_entries_for_evidence('ev-003')
        assert len(entries) == 2

    def test_unknown_evidence_returns_empty(self):
        entries = self.mgr.get_entries_for_evidence('nonexistent')
        assert entries == []


# ══════════════════════════════════════════════════════════════════════════════
# CryptoManager
# ══════════════════════════════════════════════════════════════════════════════

class TestCryptoManager:

    def setup_method(self):
        from config.crypto_manager import CryptoManager
        self.tmpdir = tempfile.mkdtemp()
        self.crypto = CryptoManager(key_dir=self.tmpdir)

    def test_keys_generated(self):
        assert Path(self.tmpdir, 'forensic_private.pem').exists()
        assert Path(self.tmpdir, 'forensic_public.pem').exists()

    def test_encrypt_returns_dict(self):
        result = self.crypto.encrypt_evidence({'sensor': 'pH', 'value': 7.2})
        assert 'ciphertext' in result
        assert 'iv' in result
        assert 'wrapped_key' in result

    def test_encrypt_decrypt_roundtrip(self):
        payload = {'evidence_id': 'test-123', 'value': 42.0}
        enc = self.crypto.encrypt_evidence(payload)
        dec = self.crypto.decrypt_evidence(enc)
        assert dec['evidence_id'] == 'test-123'
        assert dec['value'] == 42.0

    def test_decrypt_fails_with_wrong_key(self):
        from config.crypto_manager import CryptoManager
        other_dir = tempfile.mkdtemp()
        other_crypto = CryptoManager(key_dir=other_dir)
        payload = {'data': 'secret'}
        enc = self.crypto.encrypt_evidence(payload)
        with pytest.raises(Exception):
            other_crypto.decrypt_evidence(enc)

    def test_encrypt_large_payload(self):
        large = {'readings': [{'v': 7.0, 'ts': i} for i in range(100)]}
        result = self.crypto.encrypt_evidence(large)
        dec = self.crypto.decrypt_evidence(result)
        assert len(dec['readings']) == 100


# ══════════════════════════════════════════════════════════════════════════════
# ForensicCollector (basic — mocks filesystem interactions)
# ══════════════════════════════════════════════════════════════════════════════

class TestForensicCollector:

    def setup_method(self):
        from forensics.forensic_collector import ForensicCollector
        self.tmpdir = tempfile.mkdtemp()
        self.collector = ForensicCollector(evidence_dir=self.tmpdir, crypto_manager=None)

    def test_collect_evidence_returns_evidence(self):
        anomaly = {'anomaly_type': 'acid_injection', 'ensemble_score': 0.87, 'sensor_type': 'pH'}
        readings = [{'sensor_type': 'pH', 'value': 4.5, 'timestamp': '2026-01-01T00:00:00'}]
        evidence = self.collector.collect_evidence(anomaly, readings)
        assert evidence is not None
        assert evidence.evidence_id is not None

    def test_collect_evidence_hash_set(self):
        evidence = self.collector.collect_evidence({'type': 'test'}, [])
        assert evidence.evidence_hash != ''
        assert len(evidence.evidence_hash) == 64  # SHA-256 hex

    def test_hash_chain_links(self):
        e1 = self.collector.collect_evidence({'type': 'first'}, [])
        e2 = self.collector.collect_evidence({'type': 'second'}, [])
        # Second evidence's previous_hash = first's evidence_hash
        assert e2.previous_hash == e1.evidence_hash

    def test_evidence_stored_on_disk(self):
        self.collector.collect_evidence({'type': 'test'}, [])
        json_files = list(Path(self.tmpdir).glob('*.json'))
        assert len(json_files) >= 1

    def test_with_encryption(self):
        from config.crypto_manager import CryptoManager
        crypto_dir = tempfile.mkdtemp()
        crypto = CryptoManager(key_dir=crypto_dir)
        from forensics.forensic_collector import ForensicCollector
        collector = ForensicCollector(evidence_dir=self.tmpdir, crypto_manager=crypto)
        evidence = collector.collect_evidence({'type': 'encrypted_test'}, [])
        assert evidence is not None
        assert evidence.encrypted is True


# ══════════════════════════════════════════════════════════════════════════════
# Hash chain integrity
# ══════════════════════════════════════════════════════════════════════════════

class TestHashChain:

    def test_sha256_chain_computation(self):
        prev = '0' * 64
        data = json.dumps({'test': 'value'}).encode()
        h = hashlib.sha256(data).hexdigest()
        chain_h = hashlib.sha256((prev + h).encode()).hexdigest()
        assert len(chain_h) == 64
        assert chain_h != h

    def test_chain_detects_tampering(self):
        prev = '0' * 64
        data1 = json.dumps({'value': 7.0}).encode()
        h1 = hashlib.sha256(data1).hexdigest()
        # Tamper: pretend h1 was different
        tampered_h1 = 'a' * 64
        chain_real    = hashlib.sha256((prev + h1).encode()).hexdigest()
        chain_tampered = hashlib.sha256((prev + tampered_h1).encode()).hexdigest()
        assert chain_real != chain_tampered


# ══════════════════════════════════════════════════════════════════════════════
# Attack scenario classes
# ══════════════════════════════════════════════════════════════════════════════

class TestAttackScenarios:

    def test_all_scenarios_instantiate(self):
        from tests.attack_scenarios import SCENARIOS
        for name, cls in SCENARIOS.items():
            scenario = cls()
            assert scenario.name is not None

    def test_acid_injection_ph_drops(self):
        from tests.attack_scenarios import ScenarioAcidInjection
        import time
        scenario = ScenarioAcidInjection()
        # Wait slightly so some time has elapsed and attack phase begins
        scenario.start_time = __import__('datetime').datetime.now() - __import__('datetime').timedelta(seconds=90)
        readings = scenario.get_readings()
        assert any(r['sensor_type'] == 'pH' for r in readings)
        ph_readings = [r for r in readings if r['sensor_type'] == 'pH']
        assert ph_readings[0]['value'] < 7.2  # dropping

    def test_chlorine_overdose_in_range(self):
        from tests.attack_scenarios import ScenarioChlorineOverdose
        import datetime
        scenario = ScenarioChlorineOverdose()
        # Force to attack phase
        scenario.start_time = datetime.datetime.now() - datetime.timedelta(seconds=200)
        for _ in range(10):
            readings = scenario.get_readings()
            for r in readings:
                assert 0.0 <= r['value'] <= 5.0

    def test_list_scenarios_returns_all(self):
        from tests.attack_scenarios import list_scenarios
        result = list_scenarios()
        assert len(result) == 5
        names = [s['name'] for s in result]
        assert 'Acid Injection' in names

    def test_get_scenario_raises_on_unknown(self):
        from tests.attack_scenarios import get_scenario
        with pytest.raises(ValueError):
            get_scenario('nonexistent_attack')

    def test_scenario_is_active(self):
        from tests.attack_scenarios import ScenarioTemperatureSpike
        scenario = ScenarioTemperatureSpike()
        assert scenario.is_active()

    def test_scenario_expires(self):
        from tests.attack_scenarios import ScenarioTemperatureSpike
        import datetime
        scenario = ScenarioTemperatureSpike()
        scenario.start_time = datetime.datetime.now() - datetime.timedelta(minutes=10)
        assert not scenario.is_active()


# ══════════════════════════════════════════════════════════════════════════════
# Forensic tools CLI (import and basic functional test)
# ══════════════════════════════════════════════════════════════════════════════

class TestForensicTools:

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # Write a fake evidence file
        evidence = {
            'evidence_id': 'test-uuid-1234',
            'timestamp_unix': 1700000000.0,
            'timestamp_iso': '2023-11-14T22:13:20',
            'anomaly_data': {'anomaly_type': 'acid_injection', 'sensor_type': 'pH'},
            'evidence_hash': 'a' * 64,
            'previous_hash': '0' * 64,
            'hash_chain_valid': True,
            'encrypted': False,
        }
        with open(Path(self.tmpdir) / 'evidence_01.json', 'w') as f:
            json.dump(evidence, f)

    def test_verify_passes_on_valid_evidence(self):
        from forensics.forensic_tools import cmd_verify
        result = cmd_verify(Path(self.tmpdir))
        assert result == 0  # all PASS

    def test_timeline_runs_without_error(self, capsys):
        from forensics.forensic_tools import cmd_timeline
        result = cmd_timeline(Path(self.tmpdir))
        assert result == 0
        captured = capsys.readouterr()
        assert 'Timeline' in captured.out

    def test_export_json(self):
        from forensics.forensic_tools import cmd_export
        out = Path(self.tmpdir) / 'export.json'
        result = cmd_export(Path(self.tmpdir), 'json', out)
        assert result == 0
        assert out.exists()
        with open(out) as f:
            data = json.load(f)
        assert data['evidence_count'] == 1

    def test_export_csv(self):
        from forensics.forensic_tools import cmd_export
        out = Path(self.tmpdir) / 'export.csv'
        result = cmd_export(Path(self.tmpdir), 'csv', out)
        assert result == 0
        assert out.exists()

    def test_custody_empty_returns_error(self):
        from forensics.forensic_tools import cmd_custody
        result = cmd_custody(Path(self.tmpdir), None)
        assert result == 1  # no log file yet
