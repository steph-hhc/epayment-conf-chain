"""Live multi-node tests: real node processes talking over HTTP on ports 62xx."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

from conference_chain import crypto
from conference_chain import transactions as T

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "CC_INITIAL_BITS": "10", "CC_BLOCK_INTERVAL": "5", "CC_ADJUST_INTERVAL": "5"}


def url(port):
    return f"http://127.0.0.1:{port}"


def start(port, peers, data):
    cmd = [sys.executable, "-m", "conference_chain.node", "--port", str(port), "--name", f"T{port}",
           "--peers", ",".join(url(p) for p in peers), "--data", str(data)]
    proc = subprocess.Popen(cmd, cwd=ROOT, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            requests.get(url(port) + "/api/summary", timeout=0.5)
            return proc
        except requests.RequestException:
            time.sleep(0.1)
    proc.kill()
    pytest.fail(f"node {port} did not start")


def summary(port):
    return requests.get(url(port) + "/api/summary", timeout=3).json()


def wait_for(pred, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if pred():
                return True
        except requests.RequestException:
            pass
        time.sleep(0.2)
    return False


def mine_one(port):
    h = summary(port)["height"]
    requests.post(url(port) + "/api/mine", timeout=3)
    assert wait_for(lambda: summary(port)["height"] > h), f"node {port} did not mine"


@pytest.fixture
def procs():
    ps = []
    yield ps
    for p in ps:
        p.kill()


def test_three_nodes_gossip_mine_and_agree(tmp_path, procs):
    ports = [6201, 6202, 6203]
    for p in ports:
        procs.append(start(p, [q for q in ports if q != p], tmp_path))

    k = crypto.generate_private_key()
    reg = T.make_registration(k, "Net User", "net@uni.edu")
    assert requests.post(url(6201) + "/api/tx", json=reg, timeout=3).json()["ok"]
    # broadcast reaches the pending pool of every node
    assert wait_for(lambda: all(summary(p)["pending"] == 1 for p in ports))

    forged = T.make_attendance(k, "S1")
    forged["session_id"] = "S2"
    requests.post(url(6202) + "/api/tx", json=T.with_txid(forged), timeout=3)
    requests.post(url(6203) + "/api/tx", json=T.make_attendance(k, "S1"), timeout=3)
    assert wait_for(lambda: all(summary(p)["pending"] == 3 for p in ports))

    mine_one(6202)
    tip = summary(6202)["tip_hash"]
    assert wait_for(lambda: all(summary(p)["tip_hash"] == tip for p in ports))
    assert wait_for(lambda: all(summary(p)["pending"] == 0 for p in ports))  # forged one rejected/evicted everywhere
    for p in ports:
        s = summary(p)
        assert s["registered"] == 1 and s["attendance_records"] == 1
    aid = reg["attendee_id"]
    sess = requests.get(url(6203) + f"/api/query/attendee/{aid}/sessions", timeout=3).json()["sessions"]
    assert [x["session_id"] for x in sess] == ["S1"]
    assert sum(summary(6201)["balances"].values()) == 50


def test_late_joiner_syncs_and_fork_resolves(tmp_path, procs):
    # A and B start isolated and build competing chains
    procs.append(start(6211, [], tmp_path))
    procs.append(start(6212, [], tmp_path))
    k = crypto.generate_private_key()
    reg = T.make_registration(k, "Fork User", "fork@uni.edu")
    requests.post(url(6212) + "/api/tx", json=reg, timeout=3)
    mine_one(6212)                      # B: 1 block with the registration
    for _ in range(3):
        mine_one(6211)                  # A: 3 empty blocks (more work)
    assert summary(6211)["tip_hash"] != summary(6212)["tip_hash"]

    # connect them: A learns about B, then A's next block reaches B, which must reorg to A's heavier chain
    requests.post(url(6211) + "/p2p/peers", json={"url": url(6212)}, timeout=3)
    mine_one(6211)
    assert wait_for(lambda: summary(6212)["tip_hash"] == summary(6211)["tip_hash"])
    assert summary(6212)["height"] == 4
    pool = requests.get(url(6212) + "/api/mempool", timeout=3).json()["pending"]
    assert [e["tx"]["txid"] for e in pool] == [reg["txid"]]   # orphaned registration back in the pool
    assert wait_for(lambda: summary(6211)["pending"] == 1)    # ...and re-gossiped to the winning node

    # a brand-new node joining later downloads and validates the whole chain
    procs.append(start(6213, [6211], tmp_path))
    assert wait_for(lambda: summary(6213)["tip_hash"] == summary(6211)["tip_hash"])
    assert wait_for(lambda: summary(6213)["pending"] == 1)  # also picked up the pending record
    mine_one(6213)                                            # and the new node can mine it
    assert wait_for(lambda: summary(6212)["registered"] == 1 and summary(6211)["registered"] == 1)
