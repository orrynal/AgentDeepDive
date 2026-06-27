import base64
import hashlib
import struct
import hmac
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

class WeChatMsgCrypt:
    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        self.key = base64.b64decode(encoding_aes_key + "=")
        self.iv = self.key[:16]

    def verify_signature(self, signature: str, timestamp: str, nonce: str, encrypt_str: str) -> bool:
        """Verify the message signature."""
        if not signature:
            return False
        items = sorted([self.token, timestamp or "", nonce or "", encrypt_str or ""])
        concat = "".join(items).encode("utf-8")
        computed = hashlib.sha1(concat).hexdigest()  # nosec B324
        return hmac.compare_digest(computed, signature)

    def decrypt(self, encrypt_str: str) -> str:
        """Decrypt the message."""
        encrypted_bytes = base64.b64decode(encrypt_str)
        cipher = Cipher(algorithms.AES(self.key), modes.CBC(self.iv), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_bytes = decryptor.update(encrypted_bytes) + decryptor.finalize()
        
        pad_len = decrypted_bytes[-1]
        if pad_len < 1 or pad_len > 32:
            raise ValueError("Invalid padding length")
        decrypted_bytes = decrypted_bytes[:-pad_len]
        
        if len(decrypted_bytes) < 20:
            raise ValueError("Decrypted message too short")
            
        msg_len = struct.unpack(">I", decrypted_bytes[16:20])[0]
        msg = decrypted_bytes[20 : 20 + msg_len].decode("utf-8")
        received_corp_id = decrypted_bytes[20 + msg_len :].decode("utf-8")
        
        if received_corp_id != self.corp_id:
            raise ValueError("CorpID mismatch")
            
        return msg
