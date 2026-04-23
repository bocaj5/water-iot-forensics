#!/usr/bin/env python3
"""
Main entry point for Forensic Guardian Node (Raspberry Pi 2).
Run with: python main_node2.py [--mode interactive|daemon] [--log-level DEBUG|INFO|WARNING]
"""

import sys
import argparse
import logging
from datetime import datetime

# Add project root to path
sys.path.insert(0, '.')

from config.node_config import get_pi2_config
from node_roles.forensic_guardian import ForensicGuardianNode
from node_roles.heartbeat_monitor import HeartbeatMonitor
from utils.logging_manager import get_logger


def setup_logging(log_level: str = "INFO", log_file: str = None):
    """Setup logging for the node."""
    logger = get_logger("ForensicGuardian", level=log_level)

    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setLevel(getattr(logging, log_level))
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        fh.setFormatter(formatter)
        logging.getLogger().addHandler(fh)

    return logger


def interactive_mode(guardian: ForensicGuardianNode, monitor: HeartbeatMonitor):
    """Run in interactive mode with command loop."""
    logger = logging.getLogger("ForensicGuardian")

    logger.info("=" * 80)
    logger.info("FORENSIC GUARDIAN NODE (Pi 2) - INTERACTIVE MODE")
    logger.info("=" * 80)
    logger.info("Commands: status, anomalies, readings, exit")
    logger.info("=" * 80)

    try:
        while True:
            cmd = input("\n> ").strip().lower()

            if cmd == 'status':
                status = guardian.get_status()
                print(f"\nNode Status:")
                print(f"  ID: {status['node_id']}")
                print(f"  Running: {status['running']}")
                print(f"  Server Active: {status['server_active']}")
                print(f"  Receiving Data: {status['receiving_data']}")
                print(f"  Gateway Status: {status['gateway_status']}")
                print(f"  Anomalies Detected: {status['stats']['anomalies_detected']}")
                print(f"  Evidence Items: {status['stats']['evidence_items_collected']}")

            elif cmd == 'anomalies':
                summary = guardian.get_anomaly_summary()
                print(f"\nAnomaly Summary:")
                print(f"  Total Anomalies: {summary['total_anomalies']}")
                print(f"  Evidence Items: {summary['evidence_items']}")
                print(f"  Last Anomaly: {summary['last_anomaly']}")
                print(f"  Types: {summary['anomaly_types']}")

            elif cmd == 'readings':
                readings = guardian.sensor_client.get_recent_readings(5)
                print(f"\nRecent Readings ({len(readings)}):")
                for r in readings:
                    print(f"  {r.sensor_type:12} = {r.value:6.2f} {r.unit:5} "
                          f"@ {r.timestamp.strftime('%H:%M:%S')}")

            elif cmd == 'exit':
                break

            else:
                print("Unknown command")

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        guardian.stop()
        logger.info("Forensic Guardian stopped")


def daemon_mode(guardian: ForensicGuardianNode, monitor: HeartbeatMonitor):
    """Run in daemon mode (continuous background operation)."""
    logger = logging.getLogger("ForensicGuardian")

    logger.info("=" * 80)
    logger.info("FORENSIC GUARDIAN NODE (Pi 2) - DAEMON MODE")
    logger.info("=" * 80)
    logger.info("Running in background (Ctrl+C to stop)")
    logger.info("=" * 80)

    try:
        while True:
            import time
            time.sleep(60)

            # Log status every minute
            status = guardian.get_status()
            anomaly_count = status['stats']['anomalies_detected']
            evidence_count = status['stats']['evidence_items_collected']

            logger.info(
                f"Status: anomalies={anomaly_count}, "
                f"evidence={evidence_count}, "
                f"receiving={status['receiving_data']}"
            )

    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
    finally:
        guardian.stop()
        logger.info("Forensic Guardian stopped")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Forensic Guardian Node (Raspberry Pi 2)'
    )
    parser.add_argument(
        '--mode',
        choices=['interactive', 'daemon'],
        default='interactive',
        help='Operating mode'
    )
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level'
    )
    parser.add_argument(
        '--log-file',
        default=None,
        help='Log file path'
    )

    args = parser.parse_args()

    # Setup logging
    logger = setup_logging(args.log_level, args.log_file)

    try:
        # Load configuration
        config = get_pi2_config()
        logger.info(f"Configuration loaded for {config.node_id}")

        # Create guardian node
        guardian = ForensicGuardianNode(
            node_id=config.node_id,
            coap_port=config.listen_port,
            evidence_dir=config.evidence_dir
        )

        # Create heartbeat monitor
        monitor = HeartbeatMonitor(
            node_id=config.node_id,
            heartbeat_interval=config.heartbeat_interval
        )

        # Start the node
        guardian.start()

        if config.enable_heartbeat:
            monitor.start()

        # Start Flask dashboard in background thread
        from dashboard.app import run_dashboard
        run_dashboard(guardian, host='0.0.0.0', port=5000)
        logger.info("Flask dashboard started on http://0.0.0.0:5000")

        # Run in selected mode
        if args.mode == 'interactive':
            interactive_mode(guardian, monitor)
        else:
            daemon_mode(guardian, monitor)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
