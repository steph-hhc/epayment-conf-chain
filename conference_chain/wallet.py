"""Command-line attendee wallet (same encrypted keystore format as the browser wallet).

Examples
    python -m conference_chain.wallet create   --name "Alice Chan" --email alice@uni.edu
    python -m conference_chain.wallet register --wallet wallets/ATT-xxxx.json
    python -m conference_chain.wallet checkin  --wallet wallets/ATT-xxxx.json --session S1
    python -m conference_chain.wallet forge    --wallet wallets/ATT-xxxx.json --session S1 --as S3
"""
from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path

import requests

from . import crypto
from .transactions import make_attendance, make_registration, with_txid

WALLET_DIR = Path("wallets")


def create_wallet(name: str, email: str, password: str, directory: Path = WALLET_DIR) -> tuple[Path, dict]:
    key = crypto.generate_private_key()
    aid = crypto.address_from_public_key(crypto.public_key_hex(key))
    ks = crypto.encrypt_keystore(key, password, {"attendee_id": aid, "name": name, "email": email.lower()})
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{aid}.json"
    path.write_text(json.dumps(ks, indent=2))
    return path, ks


def unlock(path: str | Path, password: str):
    ks = json.loads(Path(path).read_text())
    return ks, crypto.decrypt_keystore(ks, password)


def submit(node: str, tx: dict) -> dict:
    r = requests.post(node.rstrip("/") + "/api/tx", json=tx, timeout=5)
    return r.json()


def main():
    ap = argparse.ArgumentParser(description="Conference attendee wallet")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("--name", required=True); c.add_argument("--email", required=True)
    for n in ("register", "checkin", "forge"):
        p = sub.add_parser(n)
        p.add_argument("--wallet", required=True)
        p.add_argument("--node", default="http://127.0.0.1:5001")
        if n != "register":
            p.add_argument("--session", required=True)
        if n == "forge":
            p.add_argument("--as", dest="as_session", required=True, help="session to swap in after signing")
    args = ap.parse_args()

    password = getpass.getpass("Wallet password: ")
    if args.cmd == "create":
        path, ks = create_wallet(args.name, args.email, password)
        print(f"Created wallet {path}\n  attendee_id: {ks['attendee_id']}\n  public key : {ks['public_key'][:32]}...")
        return

    ks, key = unlock(args.wallet, password)
    if args.cmd == "register":
        tx = make_registration(key, ks["name"], ks["email"])
    elif args.cmd == "checkin":
        tx = make_attendance(key, args.session)
    else:  # sign for one session, then tamper with the session field: the signature no longer matches
        tx = make_attendance(key, args.session)
        tx["session_id"] = args.as_session
        tx = with_txid(tx)
    print(json.dumps(tx, indent=2))
    print(submit(args.node, tx))


if __name__ == "__main__":
    main()
