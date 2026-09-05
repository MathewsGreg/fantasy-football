"""Cross-references FantasyPros' *weekly* rankings against live ESPN
players, as a second opinion alongside ESPN's own percent_owned/proj.

Unlike the draft-day export (one combined file, data/cheatsheet.csv),
FantasyPros' weekly product is split one page per position with no
combined "ALL" download - so this reads up to six separate files from
data/weekly/ (qb.csv, rb.csv, wr.csv, te.csv, k.csv, dst.csv), any
subset of which can be present; missing ones just mean no FantasyPros
data for that position rather than an error. Position comes from the
filename, not a column - the weekly export doesn't have a POS column at
all, since each file is already one position.

Deliberately doesn't fuse ESPN's percent_owned/points and FantasyPros'
rank/grade/projection into one score - different scales, and forcing
them together would hide real disagreement between the two instead of
surfacing it. Shown side by side; you judge.

Manual refresh: download each position's CSV from FantasyPros' weekly
rankings pages, rename to <position>.csv, drop in data/weekly/ (see
README's Phase 3 section) - nothing here fetches automatically.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEEKLY_DIR = ROOT / "data" / "weekly"

# Filename (without .csv) -> the position it holds. Lowercase to match
# how you'll actually save these; rename whatever FantasyPros calls the
# download (e.g. "FantasyPros_2026_Week_1_RB_Rankings.csv") to rb.csv.
POSITION_FILES = {"qb": "QB", "rb": "RB", "wr": "WR", "te": "TE", "k": "K", "dst": "DST"}

# Re-export sooner than this and the blend is probably still fine; past it,
# flag it - FantasyPros' own weekly refresh cycle is Tuesday, so a week-plus
# means you've likely missed at least one refresh. Measured from whichever
# position file is OLDEST, so forgetting to refresh just one position still
# gets flagged.
STALE_AFTER_DAYS = 8

_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?")
_PUNCT_RE = re.compile(r"[.'’-]")


def normalize_name(name: str) -> str:
    name = _PUNCT_RE.sub("", name.lower())
    name = _SUFFIX_RE.sub("", name)
    return re.sub(r"\s+", " ", name).strip()


def _normalize_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", h.strip().lower())


# FantasyPros' weekly export columns, as seen in an actual download:
# "RK","PLAYER NAME",TEAM,"OPP","MATCHUP ","START/SIT","PROJ. FPTS"
_HEADER_ALIASES = {
    "rank": ["rk", "rank"],
    "player": ["playername", "player", "name"],
    "team": ["team", "tm"],
    "opponent": ["opp", "opponent"],
    "matchup": ["matchup"],
    "grade": ["startsit", "grade"],
    "proj_fpts": ["projfpts", "fpts", "projpts", "projectedfpts"],
}


def _build_header_map(fieldnames: list[str]) -> dict[str, str]:
    normalized = {_normalize_header(h): h for h in fieldnames}
    resolved = {}
    for field_name, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                resolved[field_name] = normalized[alias]
                break
    if "player" not in resolved:
        raise ValueError(
            f"Couldn't find a player-name column in {fieldnames!r} - if "
            f"FantasyPros changed their weekly export format, update "
            f"_HEADER_ALIASES in fp_blend.py."
        )
    return resolved


@dataclass
class WeeklyRank:
    position: str  # from the filename, not a column
    rank: int  # rank within this position
    player: str
    team: str
    opponent: str
    grade: str  # 'A+' .. 'F', FantasyPros' own start/sit call
    proj_fpts: float | None


def _to_float(value: str) -> float | None:
    value = (value or "").strip()
    if not value or value == "-":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _load_weekly_csv(path: Path, position: str) -> list[WeeklyRank]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []
        header_map = _build_header_map(list(reader.fieldnames))

        rows = []
        for i, row in enumerate(reader, start=1):
            player = (row.get(header_map["player"]) or "").strip()
            if not player:
                continue  # blank divider rows between tiers, common in these exports
            rank_raw = (row.get(header_map.get("rank", ""), "") or "").strip()
            try:
                rank = int(float(rank_raw)) if rank_raw else i
            except ValueError:
                rank = i
            rows.append(WeeklyRank(
                position=position,
                rank=rank,
                player=player,
                team=(row.get(header_map.get("team", ""), "") or "").strip(),
                opponent=(row.get(header_map.get("opponent", ""), "") or "").strip(),
                grade=(row.get(header_map.get("grade", ""), "") or "").strip(),
                proj_fpts=_to_float(row.get(header_map.get("proj_fpts", ""), "")),
            ))
    return rows


class FantasyProsBlend:
    def __init__(self, by_name_pos: dict, by_team_dst: dict, age_days: float):
        self.by_name_pos = by_name_pos
        self.by_team_dst = by_team_dst
        self.age_days = age_days

    @property
    def stale(self) -> bool:
        return self.age_days > STALE_AFTER_DAYS

    def lookup(self, name: str, position: str, team: str) -> WeeklyRank | None:
        if position == "DST":
            return self.by_team_dst.get((team or "").upper())
        return self.by_name_pos.get((normalize_name(name), position))


def load_blend(weekly_dir: Path = WEEKLY_DIR) -> FantasyProsBlend | None:
    if not weekly_dir.exists():
        return None

    by_name_pos, by_team_dst = {}, {}
    mtimes = []
    for stem, position in POSITION_FILES.items():
        path = weekly_dir / f"{stem}.csv"
        if not path.exists():
            continue
        mtimes.append(path.stat().st_mtime)
        for wr in _load_weekly_csv(path, position):
            if position == "DST":
                by_team_dst[wr.team.upper()] = wr
            else:
                by_name_pos[(normalize_name(wr.player), position)] = wr

    if not mtimes:
        return None
    # Oldest present file, not newest - forgetting to refresh just one
    # position should still trip the staleness flag.
    age_days = (datetime.now(timezone.utc).timestamp() - min(mtimes)) / 86400
    return FantasyProsBlend(by_name_pos, by_team_dst, age_days)
