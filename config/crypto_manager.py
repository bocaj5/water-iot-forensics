"""
Cryptography manager for evidence encryption.
RSA-4096 key wrapping + AES-256-CBC evidence encryption.
"""

import logging
from typing import Tuple, Dict
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import os
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class CryptoManager:
    """Handles RSA-4096 key wrapping and AES-256-CBC evidence encryption."""

    def __init__(self, key_dir: str = "./crypto_keys"):
        """Initialize crypto manager with RSA-4096 keys."""
        self.key_dir = key_dir
        os.makedirs(key_dir, exist_ok=True)

        self.private_key_path = os.path.join(key_dir, "forensic_private.pem")
        self.public_key_path = os.path.join(key_dir, "forensic_public.pem")

        self.private_key, self.public_key = self._load_or_generate_keys()
        logger.info("CryptoManager initialized with RSA-4096 keys")

    def _load_or_generate_keys(self) -> Tuple:
        """Load existing keys or generate new RSA-4096 key pair."""
        if os.path.exists(self.private_key_path) and os.path.exists(self.public_key_path):
            try:
                with open(self.private_key_path, 'rb') as f:
                    private_key = serialization.load_pem_private_key(
                        f.read(), password=None, backend=default_backend()
                    )
                with open(self.public_key_path, 'rb') as f:
                    public_key = serialization.load_pem_public_key(
                        f.read(), backend=default_backend()
                    )
                logger.info("Loaded existing RSA-4096 keys")
                return private_key, public_key
            except Exception as e:
                logger.warning(f"Failed to load keys: {e}")

        logger.info("Generating new RSA-4096 key pair...")
        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=4096, backend=default_backend()
        )
        public_key = private_key.public_key()

        with open(self.private_key_path, 'wb') as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ))

        with open(self.public_key_path, 'wb') as f:
            f.write(public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ))

        logger.info("Generated and saved new RSA-4096 keys")
        return private_key, public_key

    def encrypt_evidence(self, evidence_data: Dict) -> Dict:
        """Encrypt evidence with AES-256-CBC and wrap key with RSA-4096."""
        try:
            json_data = json.dumps(evidence_data).encode('utf-8')
            aes_key = os.urandom(32)  # 256 bits
            iv = os.urandom(16)  # 128 bits

            cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
            encryptor = cipher.encryptor()

            padding_length = 16 - (len(json_data) % 16)
            padded_data = json_data + bytes([padding_length] * padding_length)
            ciphertext = encryptor.update(padded_data) + encryptor.finalize()

            wrapped_key = self.public_key.encrypt(
                aes_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )

            logger.info("Evidence encrypted: AES-256-CBC (key wrapped with RSA-4096)")
            return {
                'ciphertext': ciphertext.hex(),
                'iv': iv.hex(),
                'wrapped_key': wrapped_key.hex(),
                'timestamp': datetime.now().isoformat(),
                'algorithm': 'AES-256-CBC + RSA-4096'
            }
        except Exception as e:
            logger.error(f"Encryption error: {e}")
            raise

    def decrypt_evidence(self, encrypted_package: Dict) -> Dict:
        """Decrypt evidence from encrypted package."""
        try:
            wrapped_key_bytes = bytes.fromhex(encrypted_package['wrapped_key'])
            aes_key = self.private_key.decrypt(
                wrapped_key_bytes,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )

            iv = bytes.fromhex(encrypted_package['iv'])
            ciphertext = bytes.fromhex(encrypted_package['ciphertext'])

            cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            padded_data = decryptor.update(ciphertext) + decryptor.finalize()

            padding_length = padded_data[-1]
            json_data = padded_data[:-padding_length]
            evidence = json.loads(json_data.decode('utf-8'))

            logger.info("Evidence decrypted successfully")
            return evidence
        except Exception as e:
            logger.error(f"Decryption error: {e}")
            raise

    def get_key_info(self) -> Dict:
        """Get information about current cryptographic keys."""
        return {
            'key_algorithm': 'RSA-4096',
            'key_size': 4096,
            'encryption_algorithm': 'AES-256-CBC',
            'aes_key_size': 256,
            'padding': 'OAEP-SHA256',
            'keys_path': self.key_dir
        }
