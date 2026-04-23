"""CoAP server for Forensic Guardian (Pi 2) - receives sensor data from Pi 1."""

import asyncio
import json
import logging
from typing import Callable, Optional, List, Dict
from datetime import datetime

from .coap_security import decrypt as _coap_decrypt

logger = logging.getLogger(__name__)

try:
    import aiocoap
    import aiocoap.resource as resource
    AIOCOAP_AVAILABLE = True
except ImportError:
    AIOCOAP_AVAILABLE = False
    resource = None  # type: ignore
    logger.warning("aiocoap not installed - CoAP server will run in simulation mode")


_ResourceBase = resource.Resource if resource is not None else object


class SensorDataResource(_ResourceBase):
    """CoAP resource endpoint for receiving sensor data at /sensor-data."""

    def __init__(self, on_data_received: Optional[Callable] = None):
        super().__init__()
        self.on_data_received = on_data_received
        self.received_count = 0

    async def render_post(self, request):
        """Handle POST of sensor readings from Pi 1."""
        try:
            raw = _coap_decrypt(request.payload)
            payload = json.loads(raw.decode('utf-8'))
            readings = payload if isinstance(payload, list) else [payload]
            self.received_count += len(readings)

            logger.debug(f"CoAP received {len(readings)} readings")

            if self.on_data_received:
                self.on_data_received(readings)

            response = aiocoap.Message(
                code=aiocoap.CHANGED,
                payload=json.dumps({
                    'status': 'ok',
                    'received': len(readings)
                }).encode()
            )
            return response
        except Exception as e:
            logger.error(f"Error processing CoAP POST: {e}")
            return aiocoap.Message(
                code=aiocoap.INTERNAL_SERVER_ERROR,
                payload=str(e).encode()
            )

    async def render_get(self, request):
        """Handle GET - return server status."""
        status = json.dumps({
            'status': 'running',
            'received_total': self.received_count,
            'timestamp': datetime.now().isoformat()
        }).encode()
        return aiocoap.Message(payload=status)


class HeartbeatResource(_ResourceBase):
    """CoAP resource for heartbeat at /heartbeat."""

    def __init__(self):
        super().__init__()
        self.last_heartbeat = None

    async def render_post(self, request):
        self.last_heartbeat = datetime.now()
        return aiocoap.Message(
            code=aiocoap.CHANGED,
            payload=b'ok'
        )

    async def render_get(self, request):
        status = json.dumps({
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
        }).encode()
        return aiocoap.Message(payload=status)


class CoAPServer:
    """CoAP server running on Pi 2 to receive sensor data from Pi 1."""

    def __init__(self, bind_host: str = "::", port: int = 5683,
                 on_data_received: Optional[Callable] = None):
        self.bind_host = bind_host
        self.port = port
        self.on_data_received = on_data_received
        self._site = None
        self._context = None
        self._loop = None
        self._thread = None
        self.sensor_resource = None
        self.heartbeat_resource = None

    def start(self):
        """Start the CoAP server in a background thread."""
        if not AIOCOAP_AVAILABLE:
            logger.warning("CoAP server running in simulation mode (aiocoap not installed)")
            return

        import threading
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        logger.info(f"CoAP server starting on port {self.port}")

    def _run_server(self):
        """Internal: run the asyncio event loop for the CoAP server."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._start_server())
        self._loop.run_forever()

    async def _start_server(self):
        """Set up aiocoap resource tree and start serving."""
        root = resource.Site()

        self.sensor_resource = SensorDataResource(
            on_data_received=self.on_data_received
        )
        self.heartbeat_resource = HeartbeatResource()

        root.add_resource(['sensor-data'], self.sensor_resource)
        root.add_resource(['heartbeat'], self.heartbeat_resource)

        self._context = await aiocoap.Context.create_server_context(
            root, bind=(self.bind_host, self.port)
        )
        logger.info(f"CoAP server listening on port {self.port}")

    def stop(self):
        """Stop the CoAP server."""
        if self._context and self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        logger.info("CoAP server stopped")

    def get_stats(self) -> Dict:
        received = 0
        if self.sensor_resource:
            received = self.sensor_resource.received_count
        return {
            'port': self.port,
            'received_total': received,
            'last_heartbeat': (
                self.heartbeat_resource.last_heartbeat.isoformat()
                if self.heartbeat_resource and self.heartbeat_resource.last_heartbeat
                else None
            ),
        }
