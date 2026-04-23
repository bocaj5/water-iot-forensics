"""
Heartbeat Monitor - Health checking between Pi nodes.
Ensures both nodes are responsive and data flow is maintained.
"""

import logging
import threading
import time
from typing import Dict, Callable, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class HeartbeatMonitor:
    """
    Monitors health of both nodes via heartbeat protocol.
    Detects failures and triggers recovery actions.
    """

    def __init__(self, node_id: str, heartbeat_interval: float = 60.0):
        """
        Initialize heartbeat monitor.

        Args:
            node_id: This node's identifier ('pi1' or 'pi2')
            heartbeat_interval: Seconds between heartbeats
        """
        self.node_id = node_id
        self.heartbeat_interval = heartbeat_interval

        # Health tracking
        self.last_heartbeat_sent = datetime.now()
        self.last_heartbeat_received = datetime.now()
        self.heartbeat_count = 0
        self.missed_heartbeats = 0

        # Status
        self.is_monitoring = False
        self.other_node_alive = True

        # Callbacks
        self.on_node_alive: Optional[Callable] = None
        self.on_node_dead: Optional[Callable] = None
        self.on_connection_lost: Optional[Callable] = None

        # Threading
        self.monitor_thread = None
        self.lock = threading.Lock()

        logger.info(f"Heartbeat Monitor initialized for {node_id}")

    def start(self):
        """Start monitoring heartbeats."""
        if self.is_monitoring:
            logger.warning("Monitor already running")
            return

        self.is_monitoring = True
        self.monitor_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True
        )
        self.monitor_thread.start()
        logger.info("Heartbeat monitoring started")

    def stop(self):
        """Stop monitoring heartbeats."""
        self.is_monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5.0)
        logger.info("Heartbeat monitoring stopped")

    def send_heartbeat(self) -> bool:
        """
        Send heartbeat to other node.

        Returns:
            True if heartbeat sent successfully
        """
        try:
            with self.lock:
                self.last_heartbeat_sent = datetime.now()
                self.heartbeat_count += 1

            logger.debug(f"Heartbeat #{self.heartbeat_count} sent from {self.node_id}")
            return True

        except Exception as e:
            logger.error(f"Error sending heartbeat: {e}")
            return False

    def receive_heartbeat(self):
        """Record receipt of heartbeat from other node."""
        with self.lock:
            self.last_heartbeat_received = datetime.now()
            self.missed_heartbeats = 0  # Reset counter

            if not self.other_node_alive:
                self.other_node_alive = True
                if self.on_node_alive:
                    self.on_node_alive()
                logger.info("Other node is alive again")

        logger.debug(f"Heartbeat received by {self.node_id}")

    def _monitoring_loop(self):
        """Main monitoring loop - check for missed heartbeats."""
        timeout_threshold = self.heartbeat_interval * 3  # 3 missed beats = failure

        while self.is_monitoring:
            try:
                with self.lock:
                    time_since_last = (
                        datetime.now() - self.last_heartbeat_received
                    ).total_seconds()

                if time_since_last > timeout_threshold:
                    with self.lock:
                        if self.other_node_alive:
                            self.other_node_alive = False
                            self.missed_heartbeats += 1

                    if self.on_node_dead:
                        self.on_node_dead()

                    logger.warning(
                        f"Other node missing for {time_since_last:.1f}s "
                        f"(threshold: {timeout_threshold}s)"
                    )

                else:
                    # Send own heartbeat
                    self.send_heartbeat()

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")

            time.sleep(self.heartbeat_interval)

    def get_health_status(self) -> Dict:
        """Get health status of both nodes."""
        with self.lock:
            time_since_last_received = (
                datetime.now() - self.last_heartbeat_received
            ).total_seconds()

            return {
                'this_node': self.node_id,
                'monitoring_active': self.is_monitoring,
                'heartbeats_sent': self.heartbeat_count,
                'heartbeats_missed': self.missed_heartbeats,
                'other_node_alive': self.other_node_alive,
                'time_since_last_heartbeat': round(time_since_last_received, 1),
                'last_heartbeat_received': self.last_heartbeat_received.isoformat(),
                'threshold_seconds': self.heartbeat_interval * 3
            }
