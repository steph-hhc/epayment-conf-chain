"""Start a local 3-node network (Node A/B/C on ports 5001-5003).

    python run_network.py            # start (keeps existing chain data)
    python run_network.py --fresh    # start from genesis (removes ./data)
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

NODES = [("Node A", 5001), ("Node B", 5002), ("Node C", 5003)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="delete ./data and start from genesis")
    args = ap.parse_args()
    root = Path(__file__).parent
    if args.fresh and (root / "data").exists():
        shutil.rmtree(root / "data")
        print("Removed ./data, starting from genesis")

    procs = []
    for name, port in NODES:
        peers = ",".join(f"http://127.0.0.1:{p}" for _, p in NODES if p != port)
        cmd = [sys.executable, "-m", "conference_chain.node", "--port", str(port), "--name", name, "--peers", peers]
        procs.append(subprocess.Popen(cmd, cwd=root))
        time.sleep(0.5)

    print("\nConference chain network is running:")
    for name, port in NODES:
        print(f"  {name}: http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop all nodes.\n")
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
