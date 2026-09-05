"""Cross-references the FantasyPros export you already use for the draft
board (data/cheatsheet.csv) against live ESPN free agents, as a second
opinion alongside ESPN's own percent_owned. Deliberately doesn't try to
merge the two into one fused score - they're different scales (a market
ownership percentage vs. an expert-consensus ordinal rank/tier) and
forcing them into a single number would hide real disagreement between
the two instead of surfacing it. Shown side by side; you judge.

Manual refresh, same as the draft board: re-export from FantasyPros
(fantasy-football/README.md has the steps) and overwrite data/cheatsheet.csv
whenever you want fresher rankings - nothing here fetches automatically.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from ingest import load_cheatsheet

ROOT = Path(__file__).resolve().parent.parent
CHEATSHEET_PATH = ROOT / "data" / "cheatsheet.csv"

# Re-export sooner than this and the blend is probably still fine; past it,
# flag it - FantasyPros' own weekly refresh cycle is Tuesday, so a week-plus
# means you've likely missed at least one refresh.
STALE_AFTER_DAYS = 8

_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?")
_PUNCT_RE = re.compile(r"[.'’-]")


def normalize_name(name: str) -> str:
    name = _PUNCT_RE.sub("", name.lower())
    name = _SUFFIX_RE.sub("", name)
    return re.sub(r"\s+", " ", name).strip()


class FantasyProsBlend:
    def __init__(self, by_name_pos: dict, by_team_dst: dict, age_days: float):
        self.by_name_pos = by_name_pos
        self.by_team_dst = by_team_dst
        self.age_days = age_days

    @property
    def stale(self) -> bool:
        return self.age_days > STALE_AFTER_DAYS

    def lookup(self, name: str, position: str, team: str):
        """Returns the matching ingest.Player, or None."""
        if position == "DST":
            return self.by_team_dst.get((team or "").upper())
        return self.by_name_pos.get((normalize_name(name), position))


def load_blend(csv_path: Path = CHEATSHEET_PATH) -> FantasyProsBlend | None:
    if not csv_path.exists():
        return None
    age_days = (datetime.now(timezone.utc).timestamp() - csv_path.stat().st_mtime) / 86400

    players = load_cheatsheet(str(csv_path))
    by_name_pos, by_team_dst = {}, {}
    for p in players:
        if p.position == "DST":
            by_team_dst[p.team.upper()] = p
        else:
            by_name_pos[(normalize_name(p.player), p.position)] = p
    return FantasyProsBlend(by_name_pos, by_team_dst, age_days)
