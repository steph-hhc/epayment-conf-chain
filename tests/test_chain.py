import copy
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from conference_chain import config, crypto
from conference_chain import transactions as T
from conference_chain.block import compute_hash, difficulty_bits, mine, target_to_hex
from conference_chain.chain import Blockchain, validate_chain
from conference_chain.difficulty import next_target

MINER = "MNR-test"


def mine_block(chain: Blockchain, miner=MINER):
    cand, rejected = chain.build_candidate(miner)
    solved = mine(cand)
    ok, reason = chain.add_block(solved)
    assert ok, reason
    return solved, rejected


@pytest.fixture
def people():
    return {n: crypto.generate_private_key() for n in ("alice", "bob", "carol")}


@pytest.fixture
def populated(people):
    c = Blockchain()
    for name, k in people.items():
        c.add_to_mempool(T.make_registration(k, name.title(), f"{name}@uni.edu"))
    mine_block(c)
    for sid in ("S1", "S2"):
        c.add_to_mempool(T.make_attendance(people["alice"], sid))
    c.add_to_mempool(T.make_attendance(people["bob"], "S1"))
    mine_block(c)
    return c


# ---------------------------------------------------------------- cryptography
def test_signature_detects_tampering():
    k = crypto.generate_private_key()
    tx = T.make_attendance(k, "S1")
    assert T.verify_tx_signature(tx, crypto.public_key_hex(k))
    tampered = dict(tx, session_id="S2")
    assert not T.verify_tx_signature(tampered, crypto.public_key_hex(k))
    other = crypto.generate_private_key()
    assert not T.verify_tx_signature(tx, crypto.public_key_hex(other))


def test_keystore_roundtrip_and_wrong_password():
    k = crypto.generate_private_key()
    ks = crypto.encrypt_keystore(k, "correct horse", {"name": "A"})
    assert "ciphertext" in ks["crypto"] and crypto.public_key_hex(k) == ks["public_key"]
    assert crypto.public_key_hex(crypto.decrypt_keystore(ks, "correct horse")) == ks["public_key"]
    with pytest.raises(Exception):
        crypto.decrypt_keystore(ks, "wrong")


# ---------------------------------------------------------------- registration / attendance / mining
def test_register_attend_and_mine(populated, people):
    s = populated.summary()
    assert s["height"] == 2 and s["registered"] == 3 and s["attendance_records"] == 3 and s["pending"] == 0
    assert s["balances"][MINER] == 2 * config.BLOCK_REWARD


def test_miner_rejects_forged_signature(populated, people):
    forged = T.make_attendance(people["carol"], "S1")
    forged["session_id"] = "S3"  # changed after signing
    ok, _ = populated.add_to_mempool(T.with_txid(forged))
    assert ok, "pool performs only structural checks"
    _, rejected = mine_block(populated)
    assert [r["reason"] for r in rejected] == ["invalid signature"]
    assert populated.attendees_of_session("S3")["attendees"] == []


def test_impersonation_rejected(populated, people):
    """Mallory signs a certificate claiming to be Bob."""
    mallory = crypto.generate_private_key()
    tx = {"type": "ATTENDANCE", "attendee_id": crypto.address_from_public_key(crypto.public_key_hex(people["bob"])),
          "session_id": "S4", "timestamp": int(time.time())}
    tx["signature"] = crypto.sign(mallory, T.signing_payload(tx))
    populated.add_to_mempool(T.with_txid(tx))
    _, rejected = mine_block(populated)
    assert rejected[0]["reason"] == "invalid signature"


def test_duplicate_unregistered_and_replay_rejected(populated, people):
    populated.add_to_mempool(T.make_attendance(people["alice"], "S1", timestamp=int(time.time()) + 1))  # duplicate
    populated.add_to_mempool(T.make_attendance(crypto.generate_private_key(), "S1"))                     # unregistered
    populated.add_to_mempool(T.make_registration(people["bob"], "Bob 2", "bob2@uni.edu"))              # re-register
    _, rejected = mine_block(populated)
    assert sorted(r["reason"] for r in rejected) == sorted([
        "attendance already recorded for this session", "attendee is not registered", "attendee already registered"])
    replay = populated.blocks[2]["transactions"][1]
    assert populated.add_to_mempool(replay) == (False, "already confirmed on chain")


def test_register_and_checkin_in_same_block():
    c = Blockchain()
    k = crypto.generate_private_key()
    c.add_to_mempool(T.make_attendance(k, "S1"))              # arrives first
    c.add_to_mempool(T.make_registration(k, "Dan", "dan@uni.edu"))
    block, rejected = mine_block(c)
    assert not rejected and [t["type"] for t in block["transactions"]] == ["COINBASE", "REGISTER", "ATTENDANCE"]


def test_structural_checks():
    k = crypto.generate_private_key()
    assert not T.structural_check(T.make_attendance(k, "S99"))[0]
    reg = T.make_registration(k, "Eve", "eve@uni.edu")
    assert not T.structural_check(dict(reg, attendee_id="ATT-0000000000000000"))[0]
    assert not T.structural_check(dict(reg, email="not-an-email"))[0]
    assert not T.structural_check(dict(reg, extra=1))[0]


# ---------------------------------------------------------------- queries
def test_four_queries(populated, people):
    aid = {n: crypto.address_from_public_key(crypto.public_key_hex(k)) for n, k in people.items()}
    assert [s["session_id"] for s in populated.sessions_of_attendee(aid["alice"])["sessions"]] == ["S1", "S2"]
    assert {a["attendee_id"] for a in populated.attendees_of_session("S1")["attendees"]} == {aid["alice"], aid["bob"]}
    assert {p["attendee_id"] for p in populated.absentees_of_session("S1")["absentees"]} == {aid["carol"]}
    assert populated.registration_status("alice@uni.edu")["status"] == "CONFIRMED"
    assert populated.registration_status(aid["carol"])["confirmations"] == 2
    k = crypto.generate_private_key()
    populated.add_to_mempool(T.make_registration(k, "Zoe", "zoe@uni.edu"))
    assert populated.registration_status("zoe@uni.edu")["status"] == "PENDING"
    assert populated.registration_status("nobody@uni.edu")["status"] == "NOT_REGISTERED"


# ---------------------------------------------------------------- chain integrity
def test_tampering_with_mined_block_is_detected(populated):
    assert validate_chain(populated.blocks)[0]
    forged = copy.deepcopy(populated.blocks)
    forged[2]["transactions"][1]["session_id"] = "S5"
    ok, reason, _ = validate_chain(forged)
    assert not ok and "txid mismatch" in reason

    forged = copy.deepcopy(populated.blocks)
    forged[1]["nonce"] += 1
    forged[1]["hash"] = compute_hash(forged[1])  # recompute hash: PoW and the link to block 2 now fail
    assert not validate_chain(forged)[0]


def test_block_with_wrong_difficulty_rejected(populated):
    cand, _ = populated.build_candidate(MINER)
    cand["target"] = target_to_hex(int(cand["target"], 16) * 2)  # claim an easier target (2x)
    solved = mine(cand)
    ok, reason = populated.add_block(solved)
    assert not ok and reason == "block declares wrong difficulty target"


def test_wrong_coinbase_reward_rejected(populated):
    cand, _ = populated.build_candidate(MINER)
    cand["transactions"][0] = T.with_txid(dict(cand["transactions"][0], amount=1000))
    from conference_chain.block import merkle_root
    cand["merkle_root"] = merkle_root([t["txid"] for t in cand["transactions"]])
    ok, reason = populated.add_block(mine(cand))
    assert not ok and "coinbase" in reason


# ---------------------------------------------------------------- dynamic difficulty
def fake_chain(block_time: float, n_blocks: int, bits: int = 16):
    target = target_to_hex(2 ** (256 - bits))
    return [{"timestamp": 1000 + i * block_time, "target": target} for i in range(n_blocks)]


@pytest.mark.parametrize("block_time,direction", [(1.0, "up"), (20.0, "down"), (5.0, "same")])
def test_retarget_direction(block_time, direction):
    chain = fake_chain(block_time, 10)
    target, info = next_target(chain, 10)
    assert info["direction"] == direction


def test_retarget_is_proportional_and_clamped():
    t2, _ = next_target(fake_chain(2.5, 10), 10)           # 2x too fast -> exactly +1 bit
    assert difficulty_bits(t2) == pytest.approx(17.0)
    t_fast, _ = next_target(fake_chain(0.01, 10), 10)      # 500x too fast -> clamped to 4x = +2 bits
    assert difficulty_bits(t_fast) == pytest.approx(18.0)
    t_slow, _ = next_target(fake_chain(1000, 10), 10)      # clamped to 4x easier = -2 bits
    assert difficulty_bits(t_slow) == pytest.approx(14.0)


def test_no_retarget_between_intervals():
    assert next_target(fake_chain(1.0, 10), 8)[1] is None


def test_difficulty_rises_on_real_fast_chain():
    c = Blockchain()
    for _ in range(2 * config.DIFFICULTY_ADJUSTMENT_INTERVAL):
        mine_block(c)
    assert c.retargets and c.retargets[0]["direction"] == "up"
    assert c.summary()["difficulty_bits"] > config.INITIAL_DIFFICULTY_BITS


# ---------------------------------------------------------------- fork choice
def test_heavier_fork_wins_and_orphans_return_to_pool(people):
    a, b = Blockchain(), Blockchain()
    rec = T.make_registration(people["alice"], "Alice", "alice@uni.edu")
    a.add_to_mempool(rec)
    mine_block(a, "MNR-a")                       # A: 1 block containing Alice's registration
    for _ in range(3):
        mine_block(b, "MNR-b")                   # B: 3 empty blocks, more work
    ok, _ = a.try_replace_chain(b.blocks, "B")
    assert ok and a.height == 3
    assert rec["txid"] in a.mempool              # orphaned record goes back to the pool
    assert not b.try_replace_chain(a.blocks[:2], "A")[0]


# ---------------------------------------------------------------- browser wallet interoperability
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
def test_browser_wallet_signature_verifies_in_python():
    """Run the real static/wallet.js under Node's Web Crypto and verify its output in Python."""
    wallet_js = (Path(__file__).resolve().parents[1] / "conference_chain" / "static" / "wallet.js").read_text(encoding="utf-8")
    script = """
      const m = new Map();
      globalThis.localStorage = { getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, v) };
    """ + wallet_js + """
      (async () => {
        const ks = await Wallet.create("Ünïcode Name", "Browser@Uni.edu", "pw123456");
        await Wallet.unlock(ks.attendee_id, "pw123456");
        const reg = await Wallet.registration(ks.attendee_id);
        const att = await Wallet.attendance(ks.attendee_id, "S2");
        let wrong = false; try { await Wallet.unlock(ks.attendee_id, "nope"); } catch { wrong = true; }
        console.log(JSON.stringify({ ks, reg, att, wrong, txid: await Wallet.txid(att) }));
      })();
    """
    out = json.loads(subprocess.run([NODE, "-"], input=script, capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    reg, att = out["reg"], out["att"]
    assert out["wrong"] is True
    assert T.structural_check(reg)[0] and T.verify_tx_signature(reg, reg["public_key"])
    assert T.verify_tx_signature(att, reg["public_key"])
    assert out["txid"] == T.compute_txid(att)
    # the browser keystore decrypts in Python (shared format)
    assert crypto.public_key_hex(crypto.decrypt_keystore(out["ks"], "pw123456")) == reg["public_key"]

    c = Blockchain()
    c.add_to_mempool(reg); c.add_to_mempool(att)
    _, rejected = mine_block(c)
    assert not rejected and c.sessions_of_attendee(reg["attendee_id"])["sessions"][0]["session_id"] == "S2"
