import os
import sys
from pathlib import Path

# Low difficulty so the test suite mines blocks instantly.
os.environ.setdefault("CC_INITIAL_BITS", "8")
os.environ.setdefault("CC_BLOCK_INTERVAL", "5")
os.environ.setdefault("CC_ADJUST_INTERVAL", "5")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
