"""Cross-references FantasyPros' *weekly* rankings against live ESPN
players. FantasyPros' rank/grade/projection is the authoritative signal
for lineup order and waiver targets now; ESPN's own percent_owned/proj
is commentary shown alongside it, not the ranking authority.

Unlike the draft-day export (one combined file, data/cheatsheet.csv),
FantasyPros' weekly product is split one page per position with no
combined "ALL" download - so this reads whatever position files are in
data/weekly/. No renaming needed: it reads FantasyPros' own download
filenames as-is (e.g. "FantasyPros_2026_Week_1_RB_Rankings.csv"),
pulling the position and week number straight out of the filename -
the weekly export has no POS column at all, since each file's already
one position, and no year/week column either.

This means data/weekly/ doubles as a permanent archive: just keep
dropping each week's new downloads in without deleting anything, and
the loader always picks the newest (year, week) file per position and
ignores older ones. A "Flex" file (FantasyPros' RB/WR/TE-combined page)
sitting in the same folder is harmless - its filename doesn't match any
of our six real positions, so it's silently ignored; its ranks mix
positions together anyway and wouldn't be usable for "this player's WR
rank" the way we need.

Deliberately doesn't fuse ESPN's percent_owned/points and FantasyPros'
rank/grade/projection into one score - different scales, and forcing
them together would hide real disagreement between the two instead of
surfacing it. FantasyPros' rank drives the lineup/waiver ordering;
ESPN's numbers are shown alongside each pick as commentary, not blended
into the rank itself.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEEKLY_DIR = ROOT / "data" / "weekly"

_KNOWN_POSITIONS = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K", "DST": "DST", "DEF": "DST"}

# Re-export sooner than this and the blend is probably still fine; past it,
# flag it - FantasyPros' own weekly refresh cycle is Tuesday, so a week-plus
# means you've likely missed at least one refresh. Measured from whichever
# CURRENTLY-SELECTED (newest per position) file is oldest, so forgetting to
# refresh just one position still gets flagged - old archived weeks sitting
# in the folder don't count against this.
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


def parse_filename(path: Path) -> tuple[str, int, int] | None:
    """('RB', 2026, 1) from 'FantasyPros_2026_Week_1_RB_Rankings.csv', or
    None if this doesn't look like one of our six position files (e.g. a
    Flex export, or an unrelated CSV someone dropped in the folder)."""
    tokens = re.split(r"[^A-Za-z0-9]+", path.stem.upper())
    position = None
    year = None
    week = None
    for i, tok in enumerate(tokens):
        if tok in _KNOWN_POSITIONS and position is None:
            position = _KNOWN_POSITIONS[tok]
        elif tok == "WEEK" and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            week = int(tokens[i + 1])
        elif tok.isdigit() and len(tok) == 4 and year is None:
            year = int(tok)
    if position is None:
        return None
    return position, (year or 0), (week or 0)


@dataclass
class WeeklyRank:
    position: str
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
    def __init__(self, by_name_pos: dict, by_team_dst: dict, age_days: float, as_of: datetime, sources: dict):
        self.by_name_pos = by_name_pos
        self.by_team_dst = by_team_dst
        self.age_days = age_days
        # Oldest mtime among the currently-used (newest-per-position) files -
        # i.e. the same "worst case" freshness measure age_days/stale use.
        # FantasyPros is the authoritative source now even when stale (no
        # falling back to ESPN), so this is published on every report rather
        # than only surfaced once things cross STALE_AFTER_DAYS.
        self.as_of = as_of
        # {position: {"path": str, "mtime": float, "year": int, "week": int}}
        # for whichever file is currently selected per position - lets
        # weekly_report.py/snapshot.py tell "no fresher export was grabbed
        # since last run" apart from "it's simply been more than
        # STALE_AFTER_DAYS days" (STALE_AFTER_DAYS is an age threshold;
        # this is an exact same-file-as-last-time check).
        self.sources = sources

    @property
    def stale(self) -> bool:
        return self.age_days > STALE_AFTER_DAYS

    @property
    def as_of_str(self) -> str:
        return self.as_of.strftime("%Y-%m-%d")

    def lookup(self, name: str, position: str, team: str) -> WeeklyRank | None:
        if position == "DST":
            return self.by_team_dst.get((team or "").upper())
        return self.by_name_pos.get((normalize_name(name), position))


def load_blend(weekly_dir: Path = WEEKLY_DIR) -> FantasyProsBlend | None:
    if not weekly_dir.exists():
        return None

    # Pick the newest (year, week) file per position - ties broken by
    # mtime - so data/weekly/ can just accumulate every week's downloads
    # forever without anything needing to be deleted or renamed.
    best_by_position: dict[str, tuple[tuple[int, int, float], Path]] = {}
    for path in weekly_dir.glob("*.csv"):
        parsed = parse_filename(path)
        if parsed is None:
            continue  # not one of our six positions (e.g. a Flex export) - ignore
        position, year, week = parsed
        sort_key = (year, week, path.stat().st_mtime)
        current = best_by_position.get(position)
        if current is None or sort_key > current[0]:
            best_by_position[position] = (sort_key, path)

    if not best_by_position:
        return None

    by_name_pos, by_team_dst = {}, {}
    mtimes = []
    for position, (sort_key, path) in best_by_position.items():
        mtimes.append(sort_key[2])
        for wr in _load_weekly_csv(path, position):
            if position == "DST":
                by_team_dst[wr.team.upper()] = wr
            else:
                by_name_pos[(normalize_name(wr.player), position)] = wr

    sources = {
        position: {"path": str(path), "mtime": sort_key[2], "year": sort_key[0], "week": sort_key[1]}
        for position, (sort_key, path) in best_by_position.items()
    }

    oldest_mtime = min(mtimes)
    age_days = (datetime.now(timezone.utc).timestamp() - oldest_mtime) / 86400
    as_of = datetime.fromtimestamp(oldest_mtime, tz=timezone.utc)
    return FantasyProsBlend(by_name_pos, by_team_dst, age_days, as_of, sources)
