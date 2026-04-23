#!/usr/bin/env python3
"""
Main entry point for Sensor Gateway Node (Raspberry Pi 1).
Run with: python main_node1.py [--mode interactive|daemon] [--log-level DEBUG|INFO|WARNING]
"""

import sys
import argparse
import logging
from datetime import datetime

# Add project root to path
sys.path.insert(0, '.')

from config.node_config import get_pi1_config
from node_roles.sensor_gateway import SensorGatewayNode
from node_roles.heartbeat_monitor import HeartbeatMonitor
from utils.logging_manager import get_logger


def setup_logging(log_level: str = "INFO", log_file: str = None):
    """Setup logging for the node."""
    logger = get_logger("SensorGateway", level=log_level)

    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setLevel(getattr(logging, log_level))
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        fh.setFormatter(formatter)
        logging.getLogger().addHandler(fh)

    return logger


def interactive_mode(gateway: SensorGatewayNode, monitor: HeartbeatMonitor):
    """Run in interactive mode with command loop."""
    logger = logging.getLogger("SensorGateway")

    logger.info("=" * 80)
    logger.info("SENSOR GATEWAY NODE (Pi 1) - INTERACTIVE MODE")
    logger.info("=" * 80)
    logger.info("Commands: status, readings, buffer, exit")
    logger.info("=" * 80)

    try:
        while True:
            cmd = input("\n> ").strip().lower()

            if cmd == 'status':
                status = gateway.get_status()
                print(f"\nNode Status:")
                print(f"  ID: {status['node_id']}")
                print(f"  Running: {status['running']}")
                print(f"  Connected: {status['connected_to_gateway']}")
                print(f"  Buffer: {status['buffer_readings']}/{status['buffer_capacity']}")
                print(f"  Stats: {status['stats']}")

            elif cmd == 'readings':
                readings = gateway.get_recent_readings(5)
                print(f"\nRecent Readings ({len(readings)}):")
                for r in readings:
                    print(f"  {r.sensor_type:12} = {r.value:6.2f} {r.unit:5} "
                          f"@ {r.timestamp.strftime('%H:%M:%S')}")

            elif cmd == 'buffer':
                info = gateway.get_buffer_info()
                print(f"\nBuffer Info:")
                print(f"  Readings: {info['readings_count']}")
                print(f"  Capacity: {info['buffer_capacity']}")
                print(f"  Duration: {info['buffer_full_hours']} hours")
                print(f"  Oldest: {info['oldest_reading']}")
                print(f"  Newest: {info['newest_reading']}")

            elif cmd == 'exit':
                break

            else:
                print("Unknown command")

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        gateway.stop()
        logger.info("Sensor Gateway stopped")


def daemon_mode(gateway: SensorGatewayNode, monitor: HeartbeatMonitor):
    """Run in daemon mode (continuous background operation)."""
    logger = logging.getLogger("SensorGateway")

    logger.info("=" * 80)
    logger.info("SENSOR GATEWAY NODE (Pi 1) - DAEMON MODE")
    logger.info("=" * 80)
    logger.info("Running in background (Ctrl+C to stop)")
    logger.info("=" * 80)

    try:
        while True:
            import time
            time.sleep(60)

            # Log status every minute
            status = gateway.get_status()
            logger.info(
                f"Status: readings={status['buffer_readings']}, "
                f"connected={status['connected_to_gateway']}, "
                f"transmitted={status['stats']['readings_transmitted']}"
            )

    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
    finally:
        gateway.stop()
        logger.info("Sensor Gateway stopped")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Sensor Gateway Node (Raspberry Pi 1)'
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
        config = get_pi1_config()
        logger.info(f"Configuration loaded for {config.node_id}")

        # Create gateway node
        gateway = SensorGatewayNode(
            node_id=config.node_id,
            gateway_host=config.remote_host or '192.168.1.11',
            gateway_port=config.remote_port
        )

        # Create heartbeat monitor
        monitor = HeartbeatMonitor(
            node_id=config.node_id,
            heartbeat_interval=config.heartbeat_interval
        )

        # Start the node
        gateway.start(
            sensor_interval=config.sensor_read_interval,
            transmit_interval=config.data_transmission_interval
        )

        if config.enable_heartbeat:
            monitor.start()

        # Run in selected mode
        if args.mode == 'interactive':
            interactive_mode(gateway, monitor)
        else:
            daemon_mode(gateway, monitor)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
