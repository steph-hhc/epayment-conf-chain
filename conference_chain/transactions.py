"""Transaction types carried by the conference blockchain.

REGISTER    attendee binds name + email to their public key (self-signed, which
            proves they own the matching private key).
ATTENDANCE  the attendance certificate: {attendee_id, session_id, timestamp}
            signed with the attendee's private key.
COINBASE    first transaction of every block; pays the block reward to the miner.

The signed message is the canonical JSON of every field except `signature`
and `txid`, so changing any field after signing invalidates the signature.
"""
from __future__ import annotations

import re
import time

from . import config
from .crypto import (
    address_from_public_key,
    canonical_json,
    is_valid_public_key,
    public_key_hex,
    sha256_hex,
    sign,
    verify,
)

REGISTER, ATTENDANCE, COINBASE = "REGISTER", "ATTENDANCE", "COINBASE"

FIELDS = {
    REGISTER: {"type", "attendee_id", "name", "email", "public_key", "timestamp", "signature"},
    ATTENDANCE: {"type", "attendee_id", "session_id", "timestamp", "signature"},
    COINBASE: {"type", "miner", "amount", "height"},
}
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
SESSION_IDS = {s["session_id"] for s in config.SESSIONS}


# --------------------------------------------------------------------------- hashing / signing
def signing_payload(tx: dict) -> bytes:
    return canonical_json({k: v for k, v in tx.items() if k not in ("signature", "txid")})


def compute_txid(tx: dict) -> str:
    return sha256_hex(canonical_json({k: v for k, v in tx.items() if k != "txid"}))


def with_txid(tx: dict) -> dict:
    tx = dict(tx)
    tx["txid"] = compute_txid(tx)
    return tx


# --------------------------------------------------------------------------- factories
def make_registration(private_key, name: str, email: str, timestamp: int | None = None) -> dict:
    pub = public_key_hex(private_key)
    tx = {
        "type": REGISTER,
        "attendee_id": address_from_public_key(pub),
        "name": name.strip(),
        "email": email.strip().lower(),
        "public_key": pub,
        "timestamp": int(timestamp if timestamp is not None else time.time()),
    }
    tx["signature"] = sign(private_key, signing_payload(tx))
    return with_txid(tx)


def make_attendance(private_key, session_id: str, timestamp: int | None = None) -> dict:
    pub = public_key_hex(private_key)
    tx = {
        "type": ATTENDANCE,
        "attendee_id": address_from_public_key(pub),
        "session_id": session_id,
        "timestamp": int(timestamp if timestamp is not None else time.time()),
    }
    tx["signature"] = sign(private_key, signing_payload(tx))
    return with_txid(tx)


def make_coinbase(miner_address: str, height: int) -> dict:
    return with_txid({"type": COINBASE, "miner": miner_address, "amount": config.BLOCK_REWARD, "height": height})


# --------------------------------------------------------------------------- validation
def structural_check(tx: dict) -> tuple[bool, str]:
    """Cheap, stateless checks a node performs before accepting a tx into its pool.

    Signature verification is deliberately *not* done here: per the project spec
    it is the miner's job to verify every signature before packaging a record.
    (Full nodes also re-verify every signature in every block they receive.)
    """
    if not isinstance(tx, dict):
        return False, "transaction must be a JSON object"
    t = tx.get("type")
    if t not in FIELDS:
        return False, f"unknown transaction type {t!r}"
    keys = set(tx) - {"txid"}
    if keys != FIELDS[t]:
        return False, f"fields mismatch: missing {sorted(FIELDS[t] - keys)}, unexpected {sorted(keys - FIELDS[t])}"
    if tx.get("txid") and tx["txid"] != compute_txid(tx):
        return False, "txid does not match transaction contents"

    if t == REGISTER:
        if not isinstance(tx["name"], str) or tx["name"] != tx["name"].strip() or not 1 <= len(tx["name"]) <= 80:
            return False, "name must be 1-80 characters without surrounding spaces"
        if not isinstance(tx["email"], str) or not EMAIL_RE.match(tx["email"]) or tx["email"] != tx["email"].lower():
            return False, "invalid email address (must be lowercase)"
        if not isinstance(tx["public_key"], str) or not is_valid_public_key(tx["public_key"]):
            return False, "invalid P-256 public key"
        if tx["attendee_id"] != address_from_public_key(tx["public_key"]):
            return False, "attendee_id is not derived from public_key"
    if t == COINBASE:
        if type(tx["amount"]) is not int or type(tx["height"]) is not int or not isinstance(tx["miner"], str):
            return False, "malformed coinbase"
    if t in (REGISTER, ATTENDANCE) and not isinstance(tx["attendee_id"], str):
        return False, "attendee_id must be a string"
    if t == ATTENDANCE:
        if tx["session_id"] not in SESSION_IDS:
            return False, f"unknown session {tx['session_id']!r}"
    if t in (REGISTER, ATTENDANCE):
        if type(tx["timestamp"]) is not int or tx["timestamp"] > time.time() + config.MAX_FUTURE_DRIFT:
            return False, "timestamp missing or in the future"
        if not isinstance(tx["signature"], str) or len(tx["signature"]) != 128:
            return False, "signature must be 64 bytes (hex)"
    return True, "ok"


def verify_tx_signature(tx: dict, public_key: str) -> bool:
    return verify(public_key, signing_payload(tx), tx["signature"])
