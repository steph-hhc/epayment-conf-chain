# ConfChain: Blockchain Conference Registration System

DSAI 4202 E-Payment and Cryptocurrency, Group Project (3 to 4 student scope + dynamic difficulty).

A peer-to-peer proof-of-work blockchain where attendees register with a public key, sign attendance
certificates with their private key, miners verify signatures before packaging records into blocks
(and earn a block reward), and organizers query attendance. Mining difficulty retargets dynamically,
Bitcoin-style.

## Feature checklist

| Requirement | Where |
|---|---|
| Attendee generates a key pair | `static/wallet.js` (browser, Web Crypto ECDSA P-256), `wallet.py` (CLI) |
| Register name + email + public key on chain | `REGISTER` tx, self-signed (proof of key ownership), `transactions.py` |
| Private key stored securely in a wallet | AES-256-GCM keystore, key from password via PBKDF2 (600k iter.); unlocked as a non-extractable key |
| Sign attendance certificate (attendee ID, session ID, timestamp) | `ATTENDANCE` tx, `Wallet.attendance()` / `make_attendance()` |
| Broadcast to the network, pending pool on each node | `POST /api/tx` then gossip `POST /p2p/tx` to all peers, `Blockchain.mempool` |
| Miner verifies every signature; only valid records are packaged | `Blockchain.build_candidate()`; every node re-verifies in `validate_block()` |
| Miner rewards | `COINBASE` tx of 50 CONF per block, validated by consensus |
| Query 1: sessions attended by a participant | `GET /api/query/attendee/<id>/sessions` |
| Query 2: participants who attended a session | `GET /api/query/session/<sid>/attendees` |
| Query 3: registered participants who did not attend a session | `GET /api/query/session/<sid>/absentees` |
| Query 4: registration status of any attendee | `GET /api/query/status?q=<id or email or public key>` (CONFIRMED / PENDING / NOT_REGISTERED) |
| Dynamic difficulty | `difficulty.py`: retarget every N blocks, `new_target = old_target * actual / expected`, clamped x4 |

Extras: 3-node network with heaviest-chain fork choice and orphaned-record recovery, Merkle roots,
median-time-past timestamp rule, replay and duplicate protection, signature re-verification in the UI,
attack demo (forged certificate), 40 automated tests including live multi-node tests and a browser-to-Python signature check.

## Quick start (Windows, macOS, Linux)

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
python run_network.py --fresh
```

In a second terminal (optional demo data: 8 attendees, 18 check-ins, 1 forged record):

```bash
python scripts/seed_demo.py
```

Open http://127.0.0.1:5001. Use the "Connected node" picker to view Node B (5002) or Node C (5003).
Seeded wallets are in `wallets/` (password `demo1234`) and can be imported on the Wallet page.

Run the tests:

```bash
python -m pytest -q
```

## Configuration

Consensus constants live in `conference_chain/config.py`. Demo timing can be changed with
environment variables (all nodes must use the same values):

| Variable | Default | Bitcoin |
|---|---|---|
| `CC_BLOCK_INTERVAL` | 5 s | 600 s |
| `CC_ADJUST_INTERVAL` | 5 blocks | 2016 blocks |
| `CC_INITIAL_BITS` | 16 leading zero bits | n/a |

## Project layout

```
conference_chain/
  config.py         consensus parameters and the conference program (genesis)
  crypto.py         SHA-256, ECDSA P-256 sign/verify, encrypted keystore
  transactions.py   REGISTER / ATTENDANCE / COINBASE, structural checks
  block.py          block header, Merkle root, proof-of-work miner
  difficulty.py     Bitcoin-style dynamic difficulty retargeting
  chain.py          state, block/chain validation, pending pool, fork choice, 4 queries
  node.py           Flask REST API, peer-to-peer gossip, background miner
  wallet.py         command-line attendee wallet
  static/           web dashboard (no external dependencies) and browser wallet
run_network.py      starts Node A/B/C on ports 5001-5003
scripts/seed_demo.py
tests/test_chain.py
```

## Deliverables in `docs/`

| File | What |
|---|---|
| `ConfChain_Presentation.pptx` | 5 slides with speaker notes (who says what) |
| `DEMO_SCRIPT.md` | 4-minute demo run sheet split across 4 members, setup checklist, Q&A prep |
| `ConfChain_Report.docx` | Report draft: overview, design, code listings, tests, 18 figures, security, contributions, references |
| `screenshots/` | Captured end-to-end evidence (`scripts/capture_screenshots.py`) |

Regenerate after changes (network running, auto-mine on for a few minutes first):

```bash
python scripts/capture_screenshots.py
```

```bash
python docs/build_slides.py
```

```bash
python docs/build_report.py
```

## CLI wallet

```bash
python -m conference_chain.wallet create --name "Ivy Yu" --email ivy@connect.edu
```

```bash
python -m conference_chain.wallet register --wallet wallets/ATT-xxxxxxxxxxxxxxxx.json
```

```bash
python -m conference_chain.wallet checkin --wallet wallets/ATT-xxxxxxxxxxxxxxxx.json --session S5
```

```bash
python -m conference_chain.wallet forge --wallet wallets/ATT-xxxxxxxxxxxxxxxx.json --session S1 --as S5
```
