"""Block structure, Merkle root, hashing, and Proof-of-Work mining."""
from __future__ import annotations

import hashlib
import math
import threading
import time

from . import config
from .crypto import canonical_json, sha256_hex

HEADER_FIELDS = ("index", "timestamp", "previous_hash", "merkle_root", "target", "nonce", "miner")


# --------------------------------------------------------------------------- helpers
def merkle_root(txids: list[str]) -> str:
    """Bitcoin-style Merkle root: pairwise SHA-256, duplicating the last node on odd levels."""
    if not txids:
        return sha256_hex(b"")
    level = list(txids)
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [sha256_hex((level[i] + level[i + 1]).encode()) for i in range(0, len(level), 2)]
    return level[0]


def header_of(block: dict) -> dict:
    return {k: block[k] for k in HEADER_FIELDS}


def compute_hash(block: dict) -> str:
    """The block hash commits to the header only; the header commits to all txs via merkle_root."""
    return sha256_hex(canonical_json(header_of(block)))


def target_to_hex(target: int) -> str:
    return f"{target:064x}"


def target_of(block: dict) -> int:
    return int(block["target"], 16)


def difficulty_bits(target: int) -> float:
    """Equivalent number of leading zero bits required (fractional)."""
    return 256 - math.log2(target)


def block_work(target: int) -> int:
    """Expected number of hashes to find a block, used for heaviest-chain fork choice."""
    return (2 ** 256) // (target + 1)


def meets_target(block_hash: str, target: int) -> bool:
    return int(block_hash, 16) <= target


# --------------------------------------------------------------------------- genesis
def genesis_block() -> dict:
    genesis_tx = {
        "type": "GENESIS",
        "conference": config.CONFERENCE_NAME,
        "sessions": config.SESSIONS,
        "txid": sha256_hex(canonical_json({"conference": config.CONFERENCE_NAME, "sessions": config.SESSIONS})),
    }
    block = {
        "index": 0,
        "timestamp": float(config.GENESIS_TIMESTAMP),
        "previous_hash": "0" * 64,
        "merkle_root": merkle_root([genesis_tx["txid"]]),
        "target": target_to_hex(2 ** (256 - config.INITIAL_DIFFICULTY_BITS)),
        "nonce": 0,
        "miner": "GENESIS",
        "transactions": [genesis_tx],
    }
    block["hash"] = compute_hash(block)
    return block


# --------------------------------------------------------------------------- mining
def mine(block: dict, stop_event: threading.Event | None = None, progress: dict | None = None) -> dict | None:
    """Search for a nonce such that SHA-256(header) <= target.

    Speed-up: the canonical header JSON is split around the nonce so each attempt
    only hashes `prefix + str(nonce) + suffix`, and the prefix state is reused.
    Returns the solved block, or None if `stop_event` was set (e.g. a competing
    block arrived from a peer, so this work is now stale).
    """
    target = target_of(block)
    header = header_of(block)
    header["nonce"] = 0
    raw = canonical_json(header)
    marker = b'"nonce":0'
    i = raw.index(marker)
    prefix, suffix = raw[: i + len(b'"nonce":')], raw[i + len(marker):]
    base = hashlib.sha256(prefix)

    nonce, started = 0, time.time()
    while True:
        h = base.copy()
        h.update(str(nonce).encode())
        h.update(suffix)
        digest = h.hexdigest()
        if int(digest, 16) <= target:
            solved = dict(block, nonce=nonce, hash=digest)
            if progress is not None:
                progress.update(hashes=nonce + 1, seconds=time.time() - started)
            return solved
        nonce += 1
        if nonce % 20_000 == 0:
            if progress is not None:
                progress.update(hashes=nonce, seconds=time.time() - started)
            if stop_event is not None and stop_event.is_set():
                return None
