import hashlib
import hmac
import os
import re


def password_hash(password, salt=None):
    salt = os.urandom(16) if salt is None else salt
    key = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f"{salt.hex()}:{key.hex()}"


def verify(password, encoded):
    try:
        salt, _ = encoded.split(":")
        return hmac.compare_digest(password_hash(password, bytes.fromhex(salt)), encoded)
    except ValueError:
        return False


def protect(value, keep):
    from cryptography.fernet import Fernet

    if not re.fullmatch(r"[\w+-]{5,32}", value):
        raise ValueError("invalid sensitive identifier")
    cipher = Fernet(os.environ["CHARGE_PII_KEY"].encode())
    return cipher.encrypt(value.encode()), "*" * (len(value) - keep) + value[-keep:]
