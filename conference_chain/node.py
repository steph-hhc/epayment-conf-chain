"""A full node: HTTP API for wallets/organizers, peer-to-peer gossip, and a miner.

Run three of these (see run_network.py) to get a small peer-to-peer network:
transactions and blocks are broadcast to every peer, each node keeps its own
pending pool and its own copy of the chain, and forks are resolved by choosing
the valid chain with the most cumulative proof of work.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory

from . import config, crypto
from .block import difficulty_bits, mine, target_of
from .chain import Blockchain
from .transactions import ATTENDANCE, REGISTER, signing_payload, verify_tx_signature

STATIC = Path(__file__).parent / "static"


class Node:
    def __init__(self, port: int, peers: list[str], data_dir: Path, name: str):
        self.port, self.name = port, name
        self.url = f"http://127.0.0.1:{port}"
        self.peers: set[str] = {p.rstrip("/") for p in peers if p.rstrip("/") != self.url}
        self.peer_status: dict[str, dict] = {}
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        self.miner_key = self._load_or_create_miner_key()
        self.miner_address = crypto.address_from_public_key(crypto.public_key_hex(self.miner_key), prefix="MNR")

        stored = self._load_chain()
        self.chain = Blockchain(stored)
        self.chain.log("info", f"{self.name} started at {self.url}, height {self.chain.height}, "
                               f"miner address {self.miner_address}")

        self.pool = ThreadPoolExecutor(max_workers=8)
        self.stop_mining = threading.Event()
        self.mine_requests = 0
        self.auto_mine = False
        self.mining = {"active": False, "height": None, "hashes": 0, "seconds": 0, "hashrate": 0}
        self.mine_cv = threading.Condition()
        threading.Thread(target=self._miner_loop, daemon=True).start()

    # ------------------------------------------------------------------ storage
    def _load_or_create_miner_key(self):
        path = self.data_dir / "miner_keystore.json"
        password = os.getenv("CC_MINER_PASSWORD", f"miner-{self.port}")
        if path.exists():
            return crypto.decrypt_keystore(json.loads(path.read_text()), password)
        key = crypto.generate_private_key()
        path.write_text(json.dumps(crypto.encrypt_keystore(key, password, {"role": "miner", "node": self.name}), indent=2))
        return key

    def _load_chain(self):
        path = self.data_dir / "chain.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                return None
        return None

    def save(self):
        with self.chain.lock:
            data = json.dumps(self.chain.blocks)
        tmp = self.data_dir / "chain.json.tmp"
        tmp.write_text(data)
        tmp.replace(self.data_dir / "chain.json")

    # ------------------------------------------------------------------ gossip
    def _post(self, peer: str, path: str, payload: dict):
        try:
            r = requests.post(peer + path, json=payload, timeout=3)
            self.peer_status[peer] = {"online": True, "last_seen": time.time()}
            return r
        except requests.RequestException:
            self.peer_status[peer] = {"online": False, "last_seen": self.peer_status.get(peer, {}).get("last_seen")}
            return None

    def broadcast(self, path: str, payload: dict, exclude: str | None = None):
        for peer in list(self.peers):
            if peer != exclude:
                self.pool.submit(self._post, peer, path, payload)

    def broadcast_tx(self, tx: dict, exclude: str | None = None):
        self.broadcast("/p2p/tx", {"tx": tx, "sender": self.url}, exclude)

    def broadcast_block(self, block: dict, exclude: str | None = None):
        self.broadcast("/p2p/block", {"block": block, "sender": self.url}, exclude)

    def receive_block(self, block: dict, sender: str) -> tuple[bool, str]:
        idx = block.get("index", -1)
        if idx == self.chain.height + 1 and block.get("previous_hash") == self.chain.tip["hash"]:
            ok, reason = self.chain.add_block(block, source=sender)
            if ok:
                self.stop_mining.set()          # our in-progress block is now stale
                self.save()
                self.broadcast_block(block, exclude=sender)
            return ok, reason
        if idx > self.chain.height:             # we are behind or on a fork: fetch their chain
            return self.sync_from(sender)
        return False, "block does not extend our chain (stale or lighter fork)"

    def sync_from(self, peer: str) -> tuple[bool, str]:
        try:
            blocks = requests.get(peer + "/api/chain", timeout=10).json()
        except (requests.RequestException, ValueError):
            return False, f"could not fetch chain from {peer}"
        ok, reason = self.chain.try_replace_chain(blocks, source=peer)
        if ok:
            self.stop_mining.set()
            self.save()
            with self.chain.lock:  # re-gossip records orphaned by the reorg so any miner can include them
                orphaned = [e["tx"] for e in self.chain.mempool.values() if e["source"] == "reorg"]
            for tx in orphaned:
                self.broadcast_tx(tx)
        return ok, reason

    def sync_with_peers(self):
        for peer in list(self.peers):
            self.sync_from(peer)
            try:  # pick up peers' pending records too
                for e in requests.get(peer + "/api/mempool", timeout=5).json()["pending"]:
                    self.chain.add_to_mempool(e["tx"], source=peer)
            except (requests.RequestException, ValueError, KeyError):
                pass

    # ------------------------------------------------------------------ mining
    def request_mining(self, auto: bool | None = None):
        with self.mine_cv:
            if auto is None:
                self.mine_requests += 1
            else:
                self.auto_mine = auto
            self.mine_cv.notify()

    def _miner_loop(self):
        while True:
            with self.mine_cv:
                while not (self.auto_mine or self.mine_requests):
                    self.mine_cv.wait()
            self.stop_mining.clear()
            candidate, rejected = self.chain.build_candidate(self.miner_address)
            self.mining = {"active": True, "height": candidate["index"], "hashes": 0, "seconds": 0,
                           "hashrate": self.mining.get("hashrate", 0),
                           "bits": round(difficulty_bits(target_of(candidate)), 3),
                           "records": len(candidate["transactions"]) - 1, "rejected": len(rejected)}
            progress: dict = {}

            def watch():
                while self.mining["active"]:
                    if progress:
                        self.mining.update(hashes=progress["hashes"], seconds=round(progress["seconds"], 2),
                                           hashrate=int(progress["hashes"] / max(progress["seconds"], 1e-6)))
                    time.sleep(0.25)
            threading.Thread(target=watch, daemon=True).start()

            solved = mine(candidate, self.stop_mining, progress)
            self.mining["active"] = False
            if progress:
                self.mining.update(hashes=progress["hashes"], seconds=round(progress["seconds"], 2),
                                   hashrate=int(progress["hashes"] / max(progress["seconds"], 1e-6)))
            if solved is None:
                self.chain.log("info", f"Mining of #{candidate['index']} aborted: a peer found a block first")
                continue
            ok, reason = self.chain.add_block(solved, source="this node's miner")
            if ok:
                self.chain.log("mined", f"Mined block #{solved['index']} with nonce {solved['nonce']:,} in "
                                        f"{progress.get('seconds', 0):.2f}s; reward {config.BLOCK_REWARD} "
                                        f"{config.COIN_SYMBOL} to {self.miner_address}", hash=solved["hash"])
                self.save()
                self.broadcast_block(solved)
                with self.mine_cv:
                    if self.mine_requests:
                        self.mine_requests -= 1


# =========================================================================== Flask app
def block_summary(b: dict) -> dict:
    return {
        "index": b["index"], "hash": b["hash"], "previous_hash": b["previous_hash"], "timestamp": b["timestamp"],
        "miner": b["miner"], "nonce": b["nonce"], "bits": round(difficulty_bits(target_of(b)), 3),
        "merkle_root": b["merkle_root"], "tx_count": len(b["transactions"]),
        "records": sum(1 for t in b["transactions"] if t["type"] in (REGISTER, ATTENDANCE)),
    }


def create_app(node: Node) -> Flask:
    app = Flask(__name__, static_folder=None)
    ch = node.chain

    @app.after_request
    def cors(resp):  # the dashboard can talk to any node in the network
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:path>")
    def static_files(path):
        return send_from_directory(STATIC, path)

    # ---------------------------------------------------------------- info
    @app.get("/api/summary")
    def summary():
        return jsonify({
            **ch.summary(), "node": node.name, "url": node.url, "miner_address": node.miner_address,
            "auto_mine": node.auto_mine, "mining": node.mining, "conference": config.CONFERENCE_NAME,
            "peers": [{"url": p, **node.peer_status.get(p, {"online": None})} for p in sorted(node.peers)],
        })

    @app.get("/api/sessions")
    def sessions():
        with ch.lock:
            return jsonify([dict(s, attended=len(ch.state.by_session.get(s["session_id"], []))) for s in config.SESSIONS])

    @app.get("/api/chain")
    def full_chain():
        with ch.lock:
            return jsonify(ch.blocks)

    @app.get("/api/blocks")
    def blocks():
        limit = int(request.args.get("limit", 15))
        with ch.lock:
            return jsonify([block_summary(b) for b in reversed(ch.blocks[-limit:])])

    @app.get("/api/block/<int:idx>")
    def block(idx):
        with ch.lock:
            if 0 <= idx < len(ch.blocks):
                return jsonify(ch.blocks[idx])
        return jsonify({"error": "no such block"}), 404

    @app.get("/api/mempool")
    def mempool():
        with ch.lock:
            return jsonify({"pending": sorted(ch.mempool.values(), key=lambda e: e["received"])})

    @app.get("/api/events")
    def events():
        return jsonify(list(ch.events)[: int(request.args.get("limit", 60))])

    @app.get("/api/difficulty")
    def difficulty():
        return jsonify({"history": ch.difficulty_history(), "retargets": ch.retargets,
                        "target_block_time": config.BLOCK_GENERATION_INTERVAL,
                        "adjust_interval": config.DIFFICULTY_ADJUSTMENT_INTERVAL})

    # ---------------------------------------------------------------- wallets submit here
    @app.post("/api/tx")
    def submit_tx():
        tx = request.get_json(force=True, silent=True)
        ok, result = ch.add_to_mempool(tx, source="wallet")
        if not ok:
            return jsonify({"ok": False, "error": result}), 400
        node.broadcast_tx(ch.mempool[result]["tx"])
        return jsonify({"ok": True, "txid": result, "broadcast_to": sorted(node.peers)})

    @app.post("/api/mine")
    def mine_once():
        node.request_mining()
        return jsonify({"ok": True})

    @app.post("/api/automine")
    def automine():
        on = bool((request.get_json(force=True, silent=True) or {}).get("on"))
        node.request_mining(auto=on)
        return jsonify({"ok": True, "auto_mine": on})

    # ---------------------------------------------------------------- organizer queries
    @app.get("/api/query/attendee/<attendee_id>/sessions")
    def q_sessions_of(attendee_id):
        return jsonify(ch.sessions_of_attendee(attendee_id))

    @app.get("/api/query/session/<session_id>/attendees")
    def q_attendees_of(session_id):
        return jsonify(ch.attendees_of_session(session_id))

    @app.get("/api/query/session/<session_id>/absentees")
    def q_absentees_of(session_id):
        return jsonify(ch.absentees_of_session(session_id))

    @app.get("/api/query/status")
    def q_status():
        return jsonify(ch.registration_status(request.args.get("q", "")))

    @app.get("/api/search")
    def search():
        return jsonify(ch.search_attendees(request.args.get("q", "")))

    @app.get("/api/verify/<txid>")
    def verify_record(txid):
        """Independently re-check a confirmed attendance certificate's signature."""
        with ch.lock:
            h = ch.state.tx_index.get(txid)
            if h is None:
                return jsonify({"error": "transaction not on chain"}), 404
            tx = next(t for t in ch.blocks[h]["transactions"] if t["txid"] == txid)
            pub = tx.get("public_key") or ch.state.registry[tx["attendee_id"]]["public_key"]
            return jsonify({"txid": txid, "block": h, "confirmations": ch.height - h + 1,
                            "signed_payload": signing_payload(tx).decode(), "public_key": pub,
                            "signature": tx["signature"], "valid": verify_tx_signature(tx, pub)})

    # ---------------------------------------------------------------- peer to peer
    @app.post("/p2p/tx")
    def p2p_tx():
        msg = request.get_json(force=True, silent=True)
        if not isinstance(msg, dict) or "tx" not in msg:
            return jsonify({"ok": False, "result": "malformed message"}), 400
        ok, result = ch.add_to_mempool(msg["tx"], source=msg.get("sender", "peer"))
        if ok:  # gossip onward; duplicates are dropped above, so loops terminate
            node.broadcast_tx(ch.mempool[result]["tx"], exclude=msg.get("sender"))
        return jsonify({"ok": ok, "result": result})

    @app.post("/p2p/block")
    def p2p_block():
        msg = request.get_json(force=True, silent=True)
        if not isinstance(msg, dict) or not isinstance(msg.get("block"), dict):
            return jsonify({"ok": False, "reason": "malformed message"}), 400
        sender = msg.get("sender", "")
        if sender and sender != node.url:
            node.peers.add(sender)
        ok, reason = node.receive_block(msg["block"], sender)
        return jsonify({"ok": ok, "reason": reason})

    @app.post("/p2p/peers")
    def add_peer():
        url = str((request.get_json(force=True, silent=True) or {}).get("url", "")).rstrip("/")
        if url and url != node.url:
            node.peers.add(url)
        return jsonify(sorted(node.peers))

    return app


def main():
    ap = argparse.ArgumentParser(description="Run a conference-chain node")
    ap.add_argument("--port", type=int, default=5001)
    ap.add_argument("--peers", default="", help="comma-separated peer URLs")
    ap.add_argument("--name", default=None)
    ap.add_argument("--data", default="data")
    args = ap.parse_args()

    name = args.name or f"Node-{args.port}"
    node = Node(args.port, [p for p in args.peers.split(",") if p], Path(args.data) / f"node_{args.port}", name)
    for p in list(node.peers):  # announce ourselves, then catch up
        node.pool.submit(node._post, p, "/p2p/peers", {"url": node.url})
    threading.Thread(target=node.sync_with_peers, daemon=True).start()
    import logging
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    create_app(node).run(host="127.0.0.1", port=args.port, threaded=True)


if __name__ == "__main__":
    main()
