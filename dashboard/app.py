"""Flask application for the Forensic Guardian dashboard."""

import logging
import os
from flask import Flask, render_template, jsonify, request
from typing import Optional

logger = logging.getLogger(__name__)

_guardian_node = None


def create_app(guardian_node=None) -> Flask:
    """Create Flask app with a reference to the ForensicGuardianNode."""
    global _guardian_node
    _guardian_node = guardian_node

    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static',
    )
    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'dev-key-change-in-production')

    register_routes(app)
    return app


def register_routes(app: Flask):

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/api/status')
    def api_status():
        if _guardian_node is None:
            return jsonify({'error': 'Guardian node not available'}), 503
        return jsonify(_guardian_node.get_status())

    @app.route('/api/readings')
    def api_readings():
        if _guardian_node is None:
            return jsonify([])
        count = min(int(request.args.get('count', 50)), 500)
        return jsonify(_guardian_node.get_recent_readings(count=count))

    @app.route('/api/anomalies')
    def api_anomalies():
        if _guardian_node is None:
            return jsonify({})
        return jsonify(_guardian_node.get_anomaly_summary())

    @app.route('/api/evidence')
    def api_evidence():
        if _guardian_node is None:
            return jsonify([])
        try:
            from pathlib import Path
            import json
            evidence_dir = Path(_guardian_node.evidence_dir)
            items = []
            for f in sorted(evidence_dir.glob('*.json'), reverse=True)[:50]:
                if f.name.startswith('.') or f.name.endswith('.enc.json'):
                    continue
                with open(f) as fh:
                    items.append(json.load(fh))
            return jsonify(items)
        except Exception as e:
            logger.error(f"Error loading evidence: {e}")
            return jsonify([])

    @app.route('/api/chain-of-custody/<evidence_id>')
    def api_chain_of_custody(evidence_id):
        if _guardian_node is None or not hasattr(_guardian_node, 'custody_manager'):
            return jsonify({'error': 'not available'}), 503
        return jsonify(
            _guardian_node.custody_manager.get_entries_for_evidence(evidence_id)
        )

    @app.route('/api/ml-stats')
    def api_ml_stats():
        if _guardian_node is None or _guardian_node.anomaly_engine is None:
            return jsonify({})
        return jsonify(_guardian_node.anomaly_engine.get_stats())

    @app.route('/api/latest-anomaly')
    def api_latest_anomaly():
        """Returns the most recent anomaly result for live score gauge."""
        if _guardian_node is None or _guardian_node.anomaly_engine is None:
            return jsonify({})
        stats = _guardian_node.anomaly_engine.get_stats()
        latest = getattr(_guardian_node.anomaly_engine, 'latest_result', None)
        if latest is None:
            return jsonify({
                'svm_score': 0.0,
                'lstm_score': 0.0,
                'ensemble_score': 0.0,
                'is_anomaly': False,
                'anomaly_type': 'normal',
                'severity': 'NORMAL',
                'sensor_type': '--',
                'timestamp': None,
            })
        return jsonify(latest.to_dict())


def run_dashboard(guardian_node, host: str = '0.0.0.0', port: int = 5000):
    """Run the Flask dashboard in a background thread."""
    import threading
    app = create_app(guardian_node)

    def _run():
        app.run(host=host, port=port, debug=False, use_reloader=False)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    logger.info(f"Dashboard started on http://{host}:{port}")
    return app
