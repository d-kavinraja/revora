import os
import base64
from cryptography.fernet import Fernet
from app.core.config import settings

class EncryptionService:
    """
    Handles AES-256 encryption/decryption of sensitive data (e.g., API keys).
    Relies on the ENCRYPTION_KEY environment variable.
    """
    def __init__(self):
        # Fernet requires a 32 url-safe base64-encoded byte string
        key = settings.ENCRYPTION_KEY.encode('utf-8')
        try:
            self.cipher_suite = Fernet(key)
        except Exception as e:
            raise ValueError(f"Invalid ENCRYPTION_KEY. It must be 32 url-safe base64-encoded bytes. Error: {e}")

    def encrypt(self, plain_text: str) -> str:
        """Encrypt a plain text string."""
        if not plain_text:
            return ""
        encrypted_bytes = self.cipher_suite.encrypt(plain_text.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')

    def decrypt(self, encrypted_text: str) -> str:
        """Decrypt an encrypted string."""
        if not encrypted_text:
            return ""
        decrypted_bytes = self.cipher_suite.decrypt(encrypted_text.encode('utf-8'))
        return decrypted_bytes.decode('utf-8')

# Singleton instance
encryption_service = EncryptionService()
