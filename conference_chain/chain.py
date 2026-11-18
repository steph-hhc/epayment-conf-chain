"""Ledger: chain validation, world state, pending pool, block assembly, and queries."""
from __future__ import annotations

import copy
import statistics
import threading
import time
from collections import deque

from . import config
from .block import (
    block_work,
    compute_hash,
    difficulty_bits,
    genesis_block,
    meets_target,
    merkle_root,
    target_of,
    target_to_hex,
)
from .difficulty import next_target
from .transactions import (
    ATTENDANCE,
    COINBASE,
    REGISTER,
    compute_txid,
    make_coinbase,
    structural_check,
    verify_tx_signature,
)

SESSIONS = {s["session_id"]: s for s in config.SESSIONS}


# =========================================================================== state
class State:
    """World state derived by replaying every block from genesis.

    The chain is the source of truth; this is an index over it that makes the
    organizer queries O(1)/O(k) instead of scanning every block.
    """

    def __init__(self):
        self.registry: dict[str, dict] = {}         # attendee_id -> profile
        self.email_index: dict[str, str] = {}       # email -> attendee_id
        self.attendance: dict[tuple, dict] = {}     # (attendee_id, session_id) -> record
        self.by_attendee: dict[str, list] = {}
        self.by_session: dict[str, list] = {sid: [] for sid in SESSIONS}
        self.balances: dict[str, int] = {}
        self.tx_index: dict[str, int] = {}          # txid -> block height

    def clone(self) -> "State":
        return copy.deepcopy(self)

    # ---- validation of a single tx against current state ------------------
    def check(self, tx: dict, verify_signature: bool = True) -> tuple[bool, str]:
        ok, reason = structural_check(tx)
        if not ok:
            return False, reason
        txid = tx.get("txid") or compute_txid(tx)
        if txid in self.tx_index:
            return False, "transaction already confirmed (replay)"
        t = tx["type"]
        if t == REGISTER:
            if tx["attendee_id"] in self.registry:
                return False, "attendee already registered"
            if tx["email"] in self.email_index:
                return False, "email already registered"
            if verify_signature and not verify_tx_signature(tx, tx["public_key"]):
                return False, "invalid signature"
        elif t == ATTENDANCE:
            profile = self.registry.get(tx["attendee_id"])
            if profile is None:
                return False, "attendee is not registered"
            if (tx["attendee_id"], tx["session_id"]) in self.attendance:
                return False, "attendance already recorded for this session"
            if verify_signature and not verify_tx_signature(tx, profile["public_key"]):
                return False, "invalid signature"
        elif t == COINBASE:
            return False, "coinbase only allowed as first tx of a block"
        return True, "ok"

    def apply(self, tx: dict, height: int, block_ts: float) -> None:
        txid = tx["txid"]
        self.tx_index[txid] = height
        t = tx["type"]
        if t == REGISTER:
            self.registry[tx["attendee_id"]] = {
                "attendee_id": tx["attendee_id"],
                "name": tx["name"],
                "email": tx["email"],
                "public_key": tx["public_key"],
                "registered_at": tx["timestamp"],
                "block": height,
                "txid": txid,
            }
            self.email_index[tx["email"]] = tx["attendee_id"]
        elif t == ATTENDANCE:
            rec = {
                "attendee_id": tx["attendee_id"],
                "session_id": tx["session_id"],
                "timestamp": tx["timestamp"],
                "signature": tx["signature"],
                "block": height,
                "block_time": block_ts,
                "txid": txid,
            }
            self.attendance[(tx["attendee_id"], tx["session_id"])] = rec
            self.by_attendee.setdefault(tx["attendee_id"], []).append(rec)
            self.by_session.setdefault(tx["session_id"], []).append(rec)
        elif t == COINBASE:
            self.balances[tx["miner"]] = self.balances.get(tx["miner"], 0) + tx["amount"]


# =========================================================================== validation
def validate_block(block: dict, chain: list[dict], state: State, now: float | None = None) -> tuple[bool, str, State | None]:
    """Full consensus check of `block` as the next block after `chain`.

    Returns (ok, reason, new_state). `state` is not modified.
    """
    now = time.time() if now is None else now
    height = len(chain)
    prev = chain[-1]
    required = {"index", "timestamp", "previous_hash", "merkle_root", "target", "nonce", "miner", "transactions", "hash"}
    if set(block) != required:
        return False, "malformed block", None
    if block["index"] != height:
        return False, f"wrong index {block['index']} (expected {height})", None
    if block["previous_hash"] != prev["hash"]:
        return False, "previous_hash does not link to chain tip", None

    # timestamps: later than median of last 11 blocks, not too far in the future
    mtp = statistics.median(b["timestamp"] for b in chain[-config.MEDIAN_TIME_SPAN:])
    if type(block["timestamp"]) not in (int, float) or type(block["nonce"]) is not int or block["timestamp"] <= mtp:
        return False, "timestamp not after median-time-past", None
    if block["timestamp"] > now + config.MAX_FUTURE_DRIFT:
        return False, "timestamp too far in the future", None

    # proof of work with the difficulty every node derives independently
    expected_target, _ = next_target(chain, height)
    if block["target"] != target_to_hex(expected_target):
        return False, "block declares wrong difficulty target", None
    if block["hash"] != compute_hash(block):
        return False, "hash does not match header", None
    if not meets_target(block["hash"], expected_target):
        return False, "insufficient proof of work", None

    txs = block["transactions"]
    if not txs or len(txs) > config.MAX_TXS_PER_BLOCK + 1:
        return False, "bad transaction count", None
    if any(tx.get("txid") != compute_txid(tx) for tx in txs):
        return False, "txid mismatch", None
    if block["merkle_root"] != merkle_root([tx["txid"] for tx in txs]):
        return False, "merkle root mismatch", None

    coinbase = txs[0]
    ok, reason = structural_check(coinbase)
    if not ok or coinbase["type"] != COINBASE:
        return False, "first transaction must be a coinbase", None
    if coinbase["amount"] != config.BLOCK_REWARD or coinbase["height"] != height or coinbase["miner"] != block["miner"]:
        return False, "invalid coinbase (amount, height, or miner)", None

    new_state = state.clone()
    new_state.apply(coinbase, height, block["timestamp"])
    for tx in txs[1:]:
        ok, reason = new_state.check(tx, verify_signature=True)  # every node re-verifies signatures
        if not ok:
            return False, f"invalid tx {tx['txid'][:10]}: {reason}", None
        new_state.apply(tx, height, block["timestamp"])
    return True, "ok", new_state


def validate_chain(blocks: list[dict]) -> tuple[bool, str, State | None]:
    if not blocks or blocks[0] != genesis_block():
        return False, "genesis block mismatch", None
    state = State()
    for i in range(1, len(blocks)):
        ok, reason, state = validate_block(blocks[i], blocks[:i], state)
        if not ok:
            return False, f"block {i}: {reason}", None
    return True, "ok", state


def chain_work(blocks: list[dict]) -> int:
    return sum(block_work(target_of(b)) for b in blocks)


# =========================================================================== blockchain
class Blockchain:
    def __init__(self, blocks: list[dict] | None = None):
        self.lock = threading.RLock()
        self.blocks: list[dict] = [genesis_block()]
        self.state = State()
        self.mempool: dict[str, dict] = {}   # txid -> {"tx":..., "received": ts, "source": str}
        self.events: deque = deque(maxlen=200)
        self.retargets: list[dict] = []
        if blocks:
            ok, reason, state = validate_chain(blocks)
            if ok:
                self.blocks, self.state = blocks, state
                self._rebuild_retargets()
            else:
                self.log("warn", f"stored chain rejected ({reason}); starting from genesis")

    # ---- events shown in the UI -------------------------------------------
    def log(self, level: str, message: str, **data) -> None:
        self.events.appendleft({"time": time.time(), "level": level, "message": message, **data})

    @property
    def tip(self) -> dict:
        return self.blocks[-1]

    @property
    def height(self) -> int:
        return len(self.blocks) - 1

    def _rebuild_retargets(self):
        self.retargets = [info for h in range(1, len(self.blocks)) if (info := next_target(self.blocks, h)[1])]

    # ---- pending pool ------------------------------------------------------
    def add_to_mempool(self, tx: dict, source: str = "local") -> tuple[bool, str]:
        with self.lock:
            ok, reason = structural_check(tx)
            if not ok:
                return False, reason
            tx = dict(tx, txid=compute_txid(tx))
            if tx["txid"] in self.mempool:
                return False, "already in pending pool"
            if tx["txid"] in self.state.tx_index:
                return False, "already confirmed on chain"
            if len(self.mempool) >= config.MAX_MEMPOOL:
                return False, "pending pool is full"
            self.mempool[tx["txid"]] = {"tx": tx, "received": time.time(), "source": source}
            self.log("info", f"{tx['type']} {tx['txid'][:10]} added to pending pool (from {source})", txid=tx["txid"])
            return True, tx["txid"]

    def prune_mempool(self) -> None:
        """After the chain changes, evict pending records that can never be mined
        (bad signature, duplicate, already registered...). Records that depend on a
        registration still waiting in the pool are kept."""
        with self.lock:
            pending_regs = {e["tx"]["attendee_id"] for e in self.mempool.values() if e["tx"]["type"] == REGISTER}
            for txid, e in list(self.mempool.items()):
                tx = e["tx"]
                ok, reason = self.state.check(tx, verify_signature=True)
                if not ok and not (reason == "attendee is not registered" and tx["attendee_id"] in pending_regs):
                    self.mempool.pop(txid)
                    self.log("reject", f"Evicted {tx['type']} {txid[:10]} from pending pool: {reason}",
                             txid=txid, reason=reason)

    # ---- block assembly (miner) -------------------------------------------
    def build_candidate(self, miner_address: str) -> tuple[dict, list[dict]]:
        """Select pending records whose signatures verify; drop the rest.

        Returns (unsolved_block, rejected) where rejected = [{tx, reason}].
        Registrations are ordered first so an attendee can register and check
        in within the same block.
        """
        with self.lock:
            height = self.height + 1
            target, _ = next_target(self.blocks, height)
            work_state = self.state.clone()
            entries = sorted(self.mempool.values(), key=lambda e: (e["tx"]["type"] != REGISTER, e["received"]))
            accepted, rejected = [], []
            for e in entries:
                tx = e["tx"]
                if len(accepted) >= config.MAX_TXS_PER_BLOCK:
                    break
                ok, reason = work_state.check(tx, verify_signature=True)  # miner verifies each signature
                if ok:
                    work_state.apply(tx, height, time.time())
                    accepted.append(tx)
                else:
                    rejected.append({"tx": tx, "reason": reason})
            for r in rejected:
                self.mempool.pop(r["tx"]["txid"], None)
                self.log("reject", f"Miner rejected {r['tx']['type']} {r['tx']['txid'][:10]}: {r['reason']}",
                         txid=r["tx"]["txid"], reason=r["reason"])

            txs = [make_coinbase(miner_address, height)] + accepted
            ts = round(max(time.time(), statistics.median(b["timestamp"] for b in self.blocks[-config.MEDIAN_TIME_SPAN:]) + 0.001), 3)
            block = {
                "index": height,
                "timestamp": ts,
                "previous_hash": self.tip["hash"],
                "merkle_root": merkle_root([t["txid"] for t in txs]),
                "target": target_to_hex(target),
                "nonce": 0,
                "miner": miner_address,
                "transactions": txs,
            }
            return block, rejected

    # ---- adding blocks -------------------------------------------------------
    def add_block(self, block: dict, source: str = "local") -> tuple[bool, str]:
        with self.lock:
            if any(b["hash"] == block.get("hash") for b in self.blocks[-50:]):
                return False, "duplicate block"
            ok, reason, new_state = validate_block(block, self.blocks, self.state)
            if not ok:
                self.log("warn", f"Rejected block #{block.get('index')} from {source}: {reason}")
                return False, reason
            self.blocks.append(block)
            self.state = new_state
            for tx in block["transactions"]:
                self.mempool.pop(tx["txid"], None)
            self.prune_mempool()
            _, info = next_target(self.blocks[:-1], block["index"])
            if info:
                self.retargets.append(info)
                self.log("difficulty", f"Difficulty retarget at #{info['height']}: {info['old_bits']:.2f} -> "
                                       f"{info['new_bits']:.2f} bits (window took {info['actual_seconds']}s, "
                                       f"expected {info['expected_seconds']}s)", **info)
            self.log("block", f"Block #{block['index']} added from {source} ({len(block['transactions']) - 1} records, "
                              f"{difficulty_bits(target_of(block)):.2f} bits)", hash=block["hash"])
            return True, "ok"

    def try_replace_chain(self, blocks: list[dict], source: str) -> tuple[bool, str]:
        """Fork choice: adopt a competing chain only if it is valid and has more cumulative work."""
        with self.lock:
            if chain_work(blocks) <= chain_work(self.blocks):
                return False, "competing chain does not have more work"
            ok, reason, state = validate_chain(blocks)
            if not ok:
                self.log("warn", f"Rejected chain from {source}: {reason}")
                return False, reason
            new_hashes = {b["hash"] for b in blocks}
            orphaned = [tx for b in self.blocks if b["hash"] not in new_hashes for tx in b["transactions"][1:]]
            old_height = self.height
            self.blocks, self.state = blocks, state
            self._rebuild_retargets()
            for txid in [t for t in self.mempool if t in state.tx_index]:
                self.mempool.pop(txid)
            for tx in orphaned:  # return records from orphaned blocks to the pool
                if tx["txid"] not in state.tx_index:
                    self.mempool.setdefault(tx["txid"], {"tx": tx, "received": time.time(), "source": "reorg"})
            self.prune_mempool()
            self.log("reorg", f"Switched to heavier chain from {source} (height {old_height} -> {self.height}, "
                              f"{len(orphaned)} orphaned records returned to pool)")
            return True, "ok"

    # ================================================================ queries
    def _session(self, sid):
        return SESSIONS.get(sid)

    def sessions_of_attendee(self, attendee_id: str) -> dict:
        """Query 1: all sessions attended by a specific participant."""
        with self.lock:
            profile = self.state.registry.get(attendee_id)
            recs = self.state.by_attendee.get(attendee_id, [])
            return {
                "attendee": _public_profile(profile),
                "sessions": [dict(r, session=self._session(r["session_id"]), confirmations=self.height - r["block"] + 1)
                             for r in sorted(recs, key=lambda r: r["timestamp"])],
            }

    def attendees_of_session(self, session_id: str) -> dict:
        """Query 2: all participants who attended a specific session."""
        with self.lock:
            recs = self.state.by_session.get(session_id, [])
            return {
                "session": self._session(session_id),
                "attendees": [dict(r, attendee=_public_profile(self.state.registry[r["attendee_id"]]))
                              for r in sorted(recs, key=lambda r: r["timestamp"])],
            }

    def absentees_of_session(self, session_id: str) -> dict:
        """Query 3: registered participants who did NOT attend a specific session."""
        with self.lock:
            attended = {r["attendee_id"] for r in self.state.by_session.get(session_id, [])}
            absent = [p for aid, p in self.state.registry.items() if aid not in attended]
            return {
                "session": self._session(session_id),
                "registered": len(self.state.registry),
                "attended": len(attended),
                "absentees": [_public_profile(p) for p in sorted(absent, key=lambda p: p["name"].lower())],
            }

    def registration_status(self, query: str) -> dict:
        """Query 4: registration status of any attendee, by ID, email, or public key.

        Status is one of CONFIRMED (on chain, with confirmations), PENDING (in this
        node's pending pool), or NOT_REGISTERED.
        """
        with self.lock:
            q = query.strip()
            aid = q
            if "@" in q:
                aid = self.state.email_index.get(q.lower(), q)
            elif len(q) == 130:
                from .crypto import address_from_public_key
                aid = address_from_public_key(q)
            profile = self.state.registry.get(aid)
            if profile:
                return {
                    "status": "CONFIRMED",
                    "attendee": _public_profile(profile),
                    "confirmations": self.height - profile["block"] + 1,
                    "sessions_attended": len(self.state.by_attendee.get(aid, [])),
                }
            for e in self.mempool.values():
                tx = e["tx"]
                if tx["type"] == REGISTER and (tx["attendee_id"] == aid or tx["email"] == q.lower()):
                    return {"status": "PENDING", "attendee": _public_profile(tx), "txid": tx["txid"]}
            return {"status": "NOT_REGISTERED", "query": q}

    def search_attendees(self, text: str) -> list[dict]:
        with self.lock:
            t = text.strip().lower()
            return [_public_profile(p) for p in self.state.registry.values()
                    if t in p["name"].lower() or t in p["email"] or t in p["attendee_id"].lower()][:20]

    # ================================================================ summaries
    def summary(self) -> dict:
        with self.lock:
            tip = self.tip
            return {
                "height": self.height,
                "tip_hash": tip["hash"],
                "difficulty_bits": round(difficulty_bits(target_of(tip)), 3),
                "next_difficulty_bits": round(difficulty_bits(next_target(self.blocks, self.height + 1)[0]), 3),
                "total_work": str(chain_work(self.blocks)),
                "registered": len(self.state.registry),
                "attendance_records": len(self.state.attendance),
                "pending": len(self.mempool),
                "balances": self.state.balances,
                "block_interval_target": config.BLOCK_GENERATION_INTERVAL,
                "adjust_interval": config.DIFFICULTY_ADJUSTMENT_INTERVAL,
                "block_reward": config.BLOCK_REWARD,
                "coin": config.COIN_SYMBOL,
            }

    def difficulty_history(self) -> list[dict]:
        with self.lock:
            out = []
            for i, b in enumerate(self.blocks[1:], start=1):
                out.append({
                    "index": i,
                    "bits": round(difficulty_bits(target_of(b)), 3),
                    "block_time": round(b["timestamp"] - self.blocks[i - 1]["timestamp"], 3) if i > 1 else None,
                })
            return out


def _public_profile(p: dict | None) -> dict | None:
    if not p:
        return None
    return {k: p[k] for k in ("attendee_id", "name", "email", "public_key", "registered_at", "block") if k in p}
