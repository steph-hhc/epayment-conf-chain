"""Edge cases: persistence, validation corner cases, API robustness, CLI wallet."""
import copy
import time

import pytest

from conference_chain import config, crypto
from conference_chain import transactions as T
from conference_chain.block import compute_hash, merkle_root, mine
from conference_chain.chain import Blockchain, validate_chain
from conference_chain.crypto import sha256_hex
from conference_chain.node import Node, create_app
from conference_chain.wallet import create_wallet, unlock

MINER = "MNR-edge"


def mine_block(c, miner=MINER):
    cand, rejected = c.build_candidate(miner)
    ok, reason = c.add_block(mine(cand))
    assert ok, reason
    return rejected


@pytest.fixture
def chain_with_alice():
    c = Blockchain()
    k = crypto.generate_private_key()
    c.add_to_mempool(T.make_registration(k, "Alice", "alice@uni.edu"))
    c.add_to_mempool(T.make_attendance(k, "S1"))
    mine_block(c)
    return c, k


# ---------------------------------------------------------------- data structures
def test_merkle_root_odd_and_single():
    a, b, c = (sha256_hex(x.encode()) for x in "abc")
    assert merkle_root([a]) == a
    ab = sha256_hex((a + b).encode())
    cc = sha256_hex((c + c).encode())
    assert merkle_root([a, b, c]) == sha256_hex((ab + cc).encode())  # last node duplicated, as in Bitcoin


def test_chain_reload_restores_state(chain_with_alice):
    c, _ = chain_with_alice
    reloaded = Blockchain(copy.deepcopy(c.blocks))
    assert reloaded.height == c.height and reloaded.summary()["attendance_records"] == 1


def test_corrupted_stored_chain_falls_back_to_genesis(chain_with_alice):
    c, _ = chain_with_alice
    bad = copy.deepcopy(c.blocks)
    bad[1]["transactions"][1]["name"] = "Mallory"
    assert Blockchain(bad).height == 0


# ---------------------------------------------------------------- transaction rules
def test_email_case_cannot_bypass_uniqueness(chain_with_alice):
    c, _ = chain_with_alice
    k = crypto.generate_private_key()
    tx = T.make_registration(k, "Alice Two", "alice@uni.edu")
    tx["email"] = "ALICE@uni.edu"
    tx["signature"] = crypto.sign(k, T.signing_payload(tx))
    ok, reason = c.add_to_mempool(T.with_txid(tx))
    assert not ok and "lowercase" in reason


def test_future_and_bool_timestamps_rejected():
    k = crypto.generate_private_key()
    assert not T.structural_check(T.make_attendance(k, "S1", timestamp=int(time.time()) + 3600))[0]
    tx = T.make_attendance(k, "S1")
    tx["timestamp"] = True
    assert not T.structural_check(tx)[0]


def test_txid_mismatch_rejected_from_pool():
    k = crypto.generate_private_key()
    tx = T.make_attendance(k, "S1")
    tx["txid"] = "0" * 64
    ok, reason = Blockchain().add_to_mempool(tx)
    assert not ok and "txid" in reason


def test_duplicate_submission_rejected():
    c = Blockchain()
    tx = T.make_registration(crypto.generate_private_key(), "Bo", "bo@uni.edu")
    assert c.add_to_mempool(tx)[0]
    assert c.add_to_mempool(tx) == (False, "already in pending pool")


def test_pool_pruned_after_block(chain_with_alice):
    """A record that became invalid (duplicate) is evicted from every node's pool when a block arrives."""
    c, k = chain_with_alice
    other = Blockchain(copy.deepcopy(c.blocks))
    dup = T.make_attendance(k, "S2")
    c.add_to_mempool(dup); other.add_to_mempool(dup)
    cand, _ = c.build_candidate(MINER)
    block = mine(cand)
    c.add_block(block)
    later = T.make_attendance(k, "S2", timestamp=int(time.time()) + 1)  # same session again, different txid
    other.mempool.pop(dup["txid"])
    other.add_to_mempool(later)
    assert other.add_block(block)[0]
    assert later["txid"] not in other.mempool


def test_query_by_public_key_and_unknown_session(chain_with_alice):
    c, k = chain_with_alice
    assert c.registration_status(crypto.public_key_hex(k))["status"] == "CONFIRMED"
    assert c.attendees_of_session("S9")["attendees"] == []


# ---------------------------------------------------------------- block rules
def test_old_timestamp_rejected(chain_with_alice):
    c, _ = chain_with_alice
    cand, _ = c.build_candidate(MINER)
    cand["timestamp"] = c.blocks[0]["timestamp"]  # before median-time-past
    ok, reason = c.add_block(mine(cand))
    assert not ok and "median" in reason


def test_future_block_rejected(chain_with_alice):
    c, _ = chain_with_alice
    cand, _ = c.build_candidate(MINER)
    cand["timestamp"] = time.time() + 3600
    ok, reason = c.add_block(mine(cand))
    assert not ok and "future" in reason


def test_block_without_coinbase_rejected(chain_with_alice):
    c, _ = chain_with_alice
    cand, _ = c.build_candidate(MINER)
    cand["transactions"] = cand["transactions"][1:] or [T.make_attendance(crypto.generate_private_key(), "S1")]
    cand["merkle_root"] = merkle_root([t["txid"] for t in cand["transactions"]])
    assert not c.add_block(mine(cand))[0]


def test_hash_must_meet_target(chain_with_alice):
    c, _ = chain_with_alice
    cand, _ = c.build_candidate(MINER)
    solved = mine(cand)
    while int(compute_hash(solved), 16) <= int(solved["target"], 16):
        solved["nonce"] += 1
    solved["hash"] = compute_hash(solved)
    ok, reason = c.add_block(solved)
    assert not ok and reason == "insufficient proof of work"


def test_two_coinbases_rejected(chain_with_alice):
    c, _ = chain_with_alice
    cand, _ = c.build_candidate(MINER)
    cand["transactions"].append(T.make_coinbase("MNR-second", cand["index"]))
    cand["merkle_root"] = merkle_root([t["txid"] for t in cand["transactions"]])
    ok, reason = c.add_block(mine(cand))
    assert not ok and "coinbase" in reason


def test_full_chain_validates_after_many_blocks():
    c = Blockchain()
    for _ in range(12):
        mine_block(c)
    assert validate_chain(c.blocks)[0] and c.summary()["balances"][MINER] == 12 * config.BLOCK_REWARD


# ---------------------------------------------------------------- REST API robustness
@pytest.fixture
def client(tmp_path):
    node = Node(5999, [], tmp_path, "Test Node")
    return create_app(node).test_client(), node


def test_api_rejects_garbage(client):
    c, _ = client
    assert c.post("/api/tx", data="not json").status_code == 400
    assert c.post("/api/tx", json={"type": "REGISTER"}).status_code == 400
    assert c.post("/p2p/tx", data="garbage").status_code == 400
    assert c.post("/p2p/block", json={"block": "x"}).status_code == 400
    assert c.get("/api/block/999").status_code == 404
    assert c.get("/api/verify/" + "0" * 64).status_code == 404


def test_api_query_endpoints(client):
    c, node = client
    k = crypto.generate_private_key()
    assert c.post("/api/tx", json=T.make_registration(k, "Cy", "cy@uni.edu")).json["ok"]
    assert c.get("/api/query/status?q=cy@uni.edu").json["status"] == "PENDING"
    cand, _ = node.chain.build_candidate(node.miner_address)
    node.chain.add_block(mine(cand))
    aid = crypto.address_from_public_key(crypto.public_key_hex(k))
    assert c.get(f"/api/query/status?q={aid}").json["status"] == "CONFIRMED"
    assert c.post("/api/tx", json=T.make_attendance(k, "S3")).json["ok"]
    cand, _ = node.chain.build_candidate(node.miner_address)
    node.chain.add_block(mine(cand))
    sess = c.get(f"/api/query/attendee/{aid}/sessions").json["sessions"]
    assert [s["session_id"] for s in sess] == ["S3"]
    assert c.get(f"/api/verify/{sess[0]['txid']}").json["valid"] is True
    assert c.get("/api/query/session/S3/attendees").json["attendees"][0]["attendee_id"] == aid
    assert [p["attendee_id"] for p in c.get("/api/query/session/S1/absentees").json["absentees"]] == [aid]


# ---------------------------------------------------------------- CLI wallet
def test_cli_wallet_roundtrip(tmp_path):
    path, ks = create_wallet("Dee", "Dee@Uni.edu", "pw-123456", tmp_path)
    raw = path.read_text()
    assert "PRIVATE" not in raw and ks["crypto"]["iterations"] == 600_000
    _, key = unlock(path, "pw-123456")
    assert crypto.address_from_public_key(crypto.public_key_hex(key)) == ks["attendee_id"]
    with pytest.raises(Exception):
        unlock(path, "wrong")
