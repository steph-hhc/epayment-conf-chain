"""Network-wide consensus parameters.

Every node must use identical values, otherwise they will disagree on which
blocks are valid. Timing values can be overridden with environment variables so
the dynamic-difficulty mechanism can be shown within a short live demo.
"""
import os

# --- Proof of Work / dynamic difficulty (Bitcoin-style retargeting) ---------
# Bitcoin: 600 s per block, retarget every 2016 blocks.
# Demo defaults: 5 s per block, retarget every 5 blocks (visible in minutes).
BLOCK_GENERATION_INTERVAL = float(os.getenv("CC_BLOCK_INTERVAL", "5"))      # seconds
DIFFICULTY_ADJUSTMENT_INTERVAL = int(os.getenv("CC_ADJUST_INTERVAL", "5"))  # blocks
MAX_ADJUSTMENT_FACTOR = 4          # Bitcoin clamps each retarget to x4 / x(1/4)

INITIAL_DIFFICULTY_BITS = int(os.getenv("CC_INITIAL_BITS", "16"))
MIN_DIFFICULTY_BITS = 8            # easiest allowed target (protects against 0-work blocks)
MAX_TARGET = 2 ** (256 - MIN_DIFFICULTY_BITS)

# --- Incentives -------------------------------------------------------------
BLOCK_REWARD = 50                  # CONF tokens paid to the miner via the coinbase tx
COIN_SYMBOL = "CONF"

# --- Block / mempool limits ------------------------------------------------
MAX_TXS_PER_BLOCK = 200
MAX_MEMPOOL = 5000                 # pending records kept per node (spam protection)
MAX_FUTURE_DRIFT = 60              # seconds a timestamp may be ahead of local clock
MEDIAN_TIME_SPAN = 11              # block ts must exceed the median of the last 11

# --- Conference program (written into the genesis block) ---------------------
CONFERENCE_NAME = "DSAI Conference 2026"
GENESIS_TIMESTAMP = 1793664000     # 2026-11-03 00:00:00 UTC (group formation deadline)
SESSIONS = [
    {"session_id": "S1", "title": "Opening Keynote: The Future of Digital Payments", "room": "Hall A", "starts": "09:00"},
    {"session_id": "S2", "title": "Workshop: Smart Contracts in Practice", "room": "Lab 2", "starts": "10:30"},
    {"session_id": "S3", "title": "Panel: CBDCs and Stablecoins", "room": "Hall A", "starts": "13:00"},
    {"session_id": "S4", "title": "Research Talk: Scaling Proof of Work", "room": "Room 301", "starts": "14:30"},
    {"session_id": "S5", "title": "Closing: Privacy-Preserving Payments", "room": "Hall A", "starts": "16:00"},
]
