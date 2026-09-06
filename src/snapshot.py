"""Persists two things after every report run, so the next run can compare
against them:

1. Each shown player's key numbers (FantasyPros rank, ESPN percent_owned),
   so the next run can show "moved N spots/points since last time" inline
   next to that number - a signal that something happened (an injury, a
   role change, a beat-writer report) worth going and checking the news
   for. Keyed by ESPN's playerId (stable across runs, unlike names -
   handles suffixes/accents/Jr.-Sr. without needing fp_blend.py's
   normalization).

2. Which FantasyPros source file (path + mtime) was used per position, so
   the next run can tell "the export I'm using is identical to last run's"
   apart from fp_blend.py's STALE_AFTER_DAYS (an age threshold, not a
   same-file check) - the intended workflow is grabbing fresh FantasyPros
   files Tuesday/Thursday/Sunday mornings before each scheduled run, and
   this is what catches "forgot to grab this morning's files" even when
   the existing file isn't old enough to trip the staleness warning.

Tracked in git (unlike data/weekly/*.csv or data/cheatsheet.csv) - unlike
those, this is our own derived data, already published in docs/index.html,
not FantasyPros' raw export.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = ROOT / "data" / "last_snapshot.json"

# A FantasyPros rank move at or past this many spots (or an ESPN ownership
# move at or past this many points) gets visually highlighted rather than
# just shown - big enough to be worth digging into, not week-to-week
# noise. Same reasoning/judgment-call as MIN_RANK_IMPROVEMENT - revisit if
# it feels too loud or too quiet.
NOTABLE_RANK_MOVE = 5
NOTABLE_OWNERSHIP_MOVE = 10.0


def load_snapshot() -> dict:
    """{'players': {...}, 'fp_sources': {...}} - both default to {} if the
    file is missing, corrupt, or (pre-dating this field) lacks one of the
    two keys, so callers never need to guard against a missing key."""
    raw = {}
    if SNAPSHOT_PATH.exists():
        try:
            raw = json.loads(SNAPSHOT_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            raw = {}  # corrupt or unreadable - start fresh rather than crash the report
    return {"players": raw.get("players", {}), "fp_sources": raw.get("fp_sources", {})}


def save_snapshot(players: dict, fp_sources: dict) -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"players": players, "fp_sources": fp_sources}
    SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def stale_positions(old_sources: dict, new_sources: dict) -> list[str]:
    """Positions (from new_sources, i.e. this run's blend) whose FantasyPros
    source file is byte-identical-in-effect (same path AND mtime) to what
    was used last run - i.e. no fresher export was grabbed before this run
    kicked off. Empty on the very first run, or once every position has a
    prior source to compare against and all of them changed."""
    stale = []
    for pos, new_src in sorted(new_sources.items()):
        old_src = old_sources.get(pos)
        if old_src is not None and old_src.get("path") == new_src.get("path") and old_src.get("mtime") == new_src.get("mtime"):
            stale.append(pos)
    return stale


def entry(fp_rank: int | None, percent_owned: float | None) -> dict:
    return {"fp_rank": fp_rank, "percent_owned": percent_owned}


def rank_move(old: dict | None, new_fp_rank: int | None) -> dict | None:
    """{'text': '+3'/'-5', 'dir': 'up'/'down', 'notable': bool} describing
    how new_fp_rank compares to the previous snapshot, 'new' if he wasn't
    ranked last time but is now (the clearest "something changed" signal
    there is), or None if there's nothing to compare (first time this
    player's ever been snapshotted, rank unchanged, or still unranked)."""
    if old is None or new_fp_rank is None:
        return None
    old_rank = old.get("fp_rank")
    if old_rank is None:
        return {"text": "NEW", "dir": "new", "notable": True}
    delta = old_rank - new_fp_rank  # positive = rank improved (moved toward #1)
    if delta == 0:
        return None
    return {
        "text": f"{'+' if delta > 0 else ''}{delta}",
        "dir": "up" if delta > 0 else "down",
        "notable": abs(delta) >= NOTABLE_RANK_MOVE,
    }


def ownership_move(old: dict | None, new_percent_owned: float | None) -> dict | None:
    """Same shape as rank_move(), for ESPN's percent_owned - a free agent's
    ownership climbing fast is its own "everyone's grabbing him, go find
    out why" signal, independent of whether FantasyPros has re-ranked him
    yet."""
    if old is None or new_percent_owned is None or new_percent_owned < 0:
        return None
    old_owned = old.get("percent_owned")
    if old_owned is None or old_owned < 0:
        return None
    delta = round(new_percent_owned - old_owned, 1)
    if delta == 0:
        return None
    return {
        "text": f"{'+' if delta > 0 else ''}{delta:.0f}",
        "dir": "up" if delta > 0 else "down",
        "notable": abs(delta) >= NOTABLE_OWNERSHIP_MOVE,
    }
