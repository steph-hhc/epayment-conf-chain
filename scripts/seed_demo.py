"""Populate a running network with demo attendees and attendance records.

    python scripts/seed_demo.py

Creates encrypted wallets in ./wallets (password: demo1234), registers 8
attendees, submits signed attendance certificates to different nodes, adds one
forged certificate (which the miner must reject), and mines until the pool is empty.
Session S5 is left empty so it can be used for a live check-in during the demo.
"""
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conference_chain.transactions import make_attendance, make_registration, with_txid  # noqa: E402
from conference_chain.wallet import create_wallet, unlock  # noqa: E402

NODES = ["http://127.0.0.1:5001", "http://127.0.0.1:5002", "http://127.0.0.1:5003"]
PASSWORD = "demo1234"
PEOPLE = [
    ("Alice Chan", "alice.chan@connect.edu", ["S1", "S2", "S3", "S4"]),
    ("Brian Wong", "brian.wong@connect.edu", ["S1", "S3"]),
    ("Chloe Lee", "chloe.lee@connect.edu", ["S1", "S2", "S4"]),
    ("Daniel Ho", "daniel.ho@connect.edu", ["S2", "S3"]),
    ("Emily Lau", "emily.lau@connect.edu", ["S1", "S3", "S4"]),
    ("Felix Ng", "felix.ng@connect.edu", ["S1"]),
    ("Grace Tam", "grace.tam@connect.edu", ["S1", "S2", "S3"]),
    ("Henry Cheung", "henry.cheung@connect.edu", []),  # registered, attended nothing
]


def post(node, tx):
    r = requests.post(node + "/api/tx", json=tx, timeout=5).json()
    print(f"  -> {node[-4:]}: {tx['type']:<10} {tx.get('session_id', tx.get('name', '')):<14} {r}")
    return r


def mine_until_empty(node):
    for _ in range(30):
        if requests.get(node + "/api/summary", timeout=5).json()["pending"] == 0:
            return
        requests.post(node + "/api/mine", timeout=5)
        time.sleep(1.5)


def main():
    wallet_dir = Path(__file__).resolve().parents[1] / "wallets"
    keys = []
    print("Creating wallets and registering attendees")
    for i, (name, email, _) in enumerate(PEOPLE):
        path, _ = create_wallet(name, email, PASSWORD, wallet_dir)
        _, key = unlock(path, PASSWORD)
        keys.append(key)
        post(NODES[i % 3], make_registration(key, name, email))
    time.sleep(1)
    mine_until_empty(NODES[0])

    print("Submitting signed attendance certificates")
    for i, (key, (_, _, sessions)) in enumerate(zip(keys, PEOPLE)):
        for sid in sessions:
            post(NODES[(i + 1) % 3], make_attendance(key, sid))

    print("Submitting a forged certificate (signed for S1, session changed to S5 afterwards)")
    forged = make_attendance(keys[5], "S1")
    forged["session_id"] = "S5"
    post(NODES[2], with_txid(forged))
    time.sleep(1)
    mine_until_empty(NODES[1])
    print("Done. Open http://127.0.0.1:5001")


if __name__ == "__main__":
    main()
