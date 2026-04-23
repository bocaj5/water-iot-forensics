"""CoAP client for Sensor Gateway (Pi 1) - sends sensor data to Pi 2."""

import asyncio
import json
import logging
from typing import List, Dict
from datetime import datetime

from .coap_security import encrypt as _coap_encrypt

logger = logging.getLogger(__name__)

try:
    import aiocoap
    AIOCOAP_AVAILABLE = True
except ImportError:
    aiocoap = None  # type: ignore[assignment]
    AIOCOAP_AVAILABLE = False
    logger.warning("aiocoap not installed - CoAP client will run in simulation mode")


class CoAPClient:
    """CoAP client running on Pi 1 to send sensor data to Pi 2."""

    def __init__(self, server_host: str = "192.168.1.11", server_port: int = 5683):
        self.server_host = server_host
        self.server_port = server_port
        self.is_connected = False
        self.connected = False
        self.stats = {
            'messages_sent': 0,
            'messages_failed': 0,
            'last_send_time': None,
        }

    def connect(self) -> bool:
        """Mark client as ready to send."""
        self.is_connected = self.connected = True
        logger.info(f"CoAP client ready → {self.server_host}:{self.server_port}")
        return True

    def send_readings(self, readings: List[Dict]) -> bool:
        if not self.is_connected:
            return False

        if not AIOCOAP_AVAILABLE:
            self.stats['messages_sent'] += 1
            self.stats['last_send_time'] = datetime.now().isoformat()
            logger.debug(f"[SIM] Sent {len(readings)} readings to {self.server_host}")
            return True

        try:
            success = asyncio.run(self._async_send(readings))
            if success:
                self.stats['messages_sent'] += 1
                self.stats['last_send_time'] = datetime.now().isoformat()
            else:
                self.stats['messages_failed'] += 1
            return success
        except Exception as e:
            logger.error(f"CoAP send error: {e}")
            self.stats['messages_failed'] += 1
            return False

    async def _async_send(self, readings: List[Dict]) -> bool:
        assert aiocoap is not None
        uri = f"coap://{self.server_host}:{self.server_port}/sensor-data"
        payload = _coap_encrypt(json.dumps(readings).encode('utf-8'))
        ctx = await aiocoap.Context.create_client_context()
        try:
            request = aiocoap.Message(code=aiocoap.POST, uri=uri, payload=payload)
            response = await asyncio.wait_for(
                ctx.request(request).response,
                timeout=10.0
            )
            if response.code.is_successful():
                logger.debug(f"Sent {len(readings)} readings via CoAP")
                return True
            else:
                logger.warning(f"CoAP response: {response.code}")
                return False
        except asyncio.TimeoutError:
            logger.warning("CoAP send timeout")
            return False
        finally:
            await ctx.shutdown()

    def send_heartbeat(self) -> bool:
        if not self.is_connected or not AIOCOAP_AVAILABLE:
            return True

        try:
            return asyncio.run(self._async_heartbeat())
        except Exception as e:
            logger.debug(f"Heartbeat send error: {e}")
            return False

    async def _async_heartbeat(self) -> bool:
        assert aiocoap is not None
        uri = f"coap://{self.server_host}:{self.server_port}/heartbeat"
        ctx = await aiocoap.Context.create_client_context()
        try:
            request = aiocoap.Message(code=aiocoap.POST, uri=uri, payload=b'ping')
            response = await asyncio.wait_for(
                ctx.request(request).response,
                timeout=5.0
            )
            return response.code.is_successful()
        except asyncio.TimeoutError:
            return False
        finally:
            await ctx.shutdown()

    def disconnect(self):
        self.is_connected = self.connected = False
        logger.info("CoAP client disconnected")

    def get_stats(self) -> Dict:
        return self.stats.copy()
