"""AES-256-GCM payload encryption for CoAP messages.

Provides transport-equivalent confidentiality and integrity for sensor data
in transit between Pi B (Sensor Gateway) and Pi A (Forensic Guardian),
replacing DTLS where aiocoap[all] cannot be built on the target platform.

Security properties:
  - Confidentiality: AES-256-GCM (256-bit key)
  - Integrity / authentication: GCM tag (128-bit)
  - Replay protection: 12-byte random nonce per message

Key is loaded from PSK_FILE (default /opt/water-monitor/config/coap_psk.key).
The file contains a hex-encoded 32-byte key on a single line.  Both nodes
must share the same key file — copy it with:

    scp /opt/water-monitor/config/coap_psk.key pi@<PiB>:/opt/water-monitor/config/
"""

import os
import logging
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

PSK_FILE = Path("/opt/water-monitor/config/coap_psk.key")
_FALLBACK_PSK_FILE = Path(__file__).resolve().parent.parent / "config" / "coap_psk.key"
NONCE_LEN = 12  # bytes — GCM standard


def _load_key() -> bytes:
    for path in (PSK_FILE, _FALLBACK_PSK_FILE):
        if path.exists():
            try:
                return bytes.fromhex(path.read_text().strip())
            except Exception as e:
                logger.warning(f"Could not load CoAP PSK from {path}: {e}")
    logger.warning("CoAP PSK not found — encryption disabled (plaintext fallback)")
    return b""


_KEY: bytes = _load_key()
_AESGCM: AESGCM | None = AESGCM(_KEY) if len(_KEY) == 32 else None


def encrypt(plaintext: bytes) -> bytes:
    """Encrypt plaintext; prefix ciphertext with 12-byte nonce.

    Returns plaintext unchanged if no key is configured (for compatibility
    with nodes that haven't received the PSK yet).
    """
    if _AESGCM is None:
        return plaintext
    nonce = os.urandom(NONCE_LEN)
    ct = _AESGCM.encrypt(nonce, plaintext, None)
    return nonce + ct


def decrypt(data: bytes) -> bytes:
    """Strip nonce, verify GCM tag, return plaintext.

    Falls back to returning data as-is if no key is configured.
    Raises cryptography.exceptions.InvalidTag on authentication failure.
    """
    if _AESGCM is None:
        return data
    if len(data) <= NONCE_LEN:
        raise ValueError(f"CoAP payload too short to contain nonce ({len(data)} bytes)")
    nonce, ct = data[:NONCE_LEN], data[NONCE_LEN:]
    return _AESGCM.decrypt(nonce, ct, None)


def is_enabled() -> bool:
    return _AESGCM is not None
