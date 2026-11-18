"""Dynamic difficulty adjustment (Bitcoin-style retargeting).

Every DIFFICULTY_ADJUSTMENT_INTERVAL blocks, compare how long the last window of
blocks actually took with how long it *should* have taken:

    expected = DIFFICULTY_ADJUSTMENT_INTERVAL * BLOCK_GENERATION_INTERVAL
    new_target = old_target * actual / expected

* blocks came too fast  (actual < expected) -> target shrinks -> difficulty rises
* blocks came too slow  (actual > expected) -> target grows   -> difficulty falls

As in Bitcoin, `actual` is clamped to [expected/4, expected*4] so one retarget
can change difficulty by at most 4x, and the target can never exceed MAX_TARGET.
Working with the integer target (instead of whole "leading zero" counts) allows
fine-grained steps, e.g. 18.0 -> 18.7 bits, rather than doubling/halving.

Every node computes the expected target independently from the chain itself,
so a block that declares any other target is rejected.
"""
from __future__ import annotations

from . import config
from .block import difficulty_bits, target_of


def next_target(chain: list[dict], height: int) -> tuple[int, dict | None]:
    """Target the block at `height` must use, given chain[0:height].

    Returns (target, retarget_info). retarget_info is None when no adjustment
    happens at this height.
    """
    n = config.DIFFICULTY_ADJUSTMENT_INTERVAL
    prev_target = target_of(chain[height - 1])
    first = height - 1 - n  # window spans n block intervals: chain[first] .. chain[height-1]
    if height % n != 0 or first < 1:  # skip windows that would include the genesis timestamp
        return prev_target, None

    expected = n * config.BLOCK_GENERATION_INTERVAL
    actual = chain[height - 1]["timestamp"] - chain[first]["timestamp"]
    clamped = min(max(actual, expected / config.MAX_ADJUSTMENT_FACTOR), expected * config.MAX_ADJUSTMENT_FACTOR)

    new_target = prev_target * int(clamped * 1000) // int(expected * 1000)
    new_target = max(1, min(new_target, config.MAX_TARGET))

    info = {
        "height": height,
        "window": [first, height - 1],
        "expected_seconds": round(expected, 2),
        "actual_seconds": round(actual, 2),
        "old_bits": round(difficulty_bits(prev_target), 3),
        "new_bits": round(difficulty_bits(new_target), 3),
        "direction": "up" if new_target < prev_target else ("down" if new_target > prev_target else "same"),
    }
    return new_target, info
