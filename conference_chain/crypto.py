"""Cryptographic primitives: hashing, ECDSA keys, signatures, and the wallet keystore.

Design choices
--------------
* ECDSA over NIST P-256 with SHA-256. P-256 is supported natively by the browser
  Web Crypto API, so attendees can generate and keep their private key inside
  their own browser wallet; the node never sees it.
* Public keys travel as the 65-byte uncompressed SEC1 point (hex).
* Signatures travel as raw r||s (64 bytes, IEEE P1363), which is what Web Crypto
  produces. We convert to DER internally for the `cryptography` library.
* Keystores are encrypted with AES-256-GCM using a key derived from the wallet
  password via PBKDF2-HMAC-SHA256. The same format is used by the browser wallet
  and by the Python CLI wallet, so a keystore can move between them.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

CURVE = ec.SECP256R1()
KDF_ITERATIONS = 600_000  # OWASP Password Storage Cheat Sheet: PBKDF2-HMAC-SHA256


# --------------------------------------------------------------------------- hashing
def canonical_json(obj: Any) -> bytes:
    """Deterministic serialization. Browser and Python must produce identical bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def address_from_public_key(public_key_hex: str, prefix: str = "ATT") -> str:
    """Short, unique identifier derived from the public key (like a Bitcoin address)."""
    return f"{prefix}-{sha256_hex(bytes.fromhex(public_key_hex))[:16]}"


# --------------------------------------------------------------------------- keys
def generate_private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(CURVE)


def public_key_hex(private_key: ec.EllipticCurvePrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return raw.hex()


def load_public_key(public_key_hex_str: str) -> ec.EllipticCurvePublicKey:
    return ec.EllipticCurvePublicKey.from_encoded_point(CURVE, bytes.fromhex(public_key_hex_str))


def is_valid_public_key(public_key_hex_str: str) -> bool:
    try:
        load_public_key(public_key_hex_str)
        return len(public_key_hex_str) == 130
    except Exception:
        return False


# --------------------------------------------------------------------------- signatures
def sign(private_key: ec.EllipticCurvePrivateKey, message: bytes) -> str:
    der = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex()


def verify(public_key_hex_str: str, message: bytes, signature_hex: str) -> bool:
    try:
        raw = bytes.fromhex(signature_hex)
        if len(raw) != 64:
            return False
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        load_public_key(public_key_hex_str).verify(der, message, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- keystore
def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _unb64(s: str) -> bytes:
    return base64.b64decode(s)


def _derive_key(password: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def encrypt_keystore(private_key: ec.EllipticCurvePrivateKey, password: str, meta: dict) -> dict:
    """Encrypt a private key (PKCS#8 DER) with a password. Returns a JSON-able keystore."""
    pkcs8 = private_key.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(_derive_key(password, salt, KDF_ITERATIONS)).encrypt(iv, pkcs8, None)
    return {
        "version": 1,
        **meta,
        "public_key": public_key_hex(private_key),
        "crypto": {
            "kdf": "PBKDF2-SHA256",
            "iterations": KDF_ITERATIONS,
            "salt": _b64(salt),
            "cipher": "AES-256-GCM",
            "iv": _b64(iv),
            "ciphertext": _b64(ct),
        },
    }


def decrypt_keystore(keystore: dict, password: str) -> ec.EllipticCurvePrivateKey:
    c = keystore["crypto"]
    key = _derive_key(password, _unb64(c["salt"]), int(c["iterations"]))
    pkcs8 = AESGCM(key).decrypt(_unb64(c["iv"]), _unb64(c["ciphertext"]), None)  # raises on wrong password
    return serialization.load_der_private_key(pkcs8, password=None)
