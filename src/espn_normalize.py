"""Normalize espn_api's raw position/slot strings to our canonical set
(QB/RB/WR/TE/K/DST/FLEX/BE/IR). Its POSITION_MAP uses ESPN's own labels
directly ('D/ST', 'RB/WR/TE', ...) which don't match the rest of this
project's conventions (ingest.py does the equivalent normalization for
FantasyPros' export).
"""

from __future__ import annotations

_POSITION_ALIASES = {
    "D/ST": "DST",
    "DST": "DST",
    "DEF": "DST",
}

_FLEX_SLOT_NAMES = {"RB/WR/TE", "RB/WR", "WR/TE", "FLEX", "OP"}


def normalize_position(raw: str) -> str:
    return _POSITION_ALIASES.get(raw, raw)


def normalize_slot(raw: str) -> str:
    """A lineupSlot string as espn_api reports it -> our canonical name.
    Bench/IR pass through unchanged (lineup.py checks for them by name)."""
    if raw in _FLEX_SLOT_NAMES:
        return "FLEX"
    return normalize_position(raw)
