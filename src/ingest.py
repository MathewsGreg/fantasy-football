"""Parse a FantasyPros rankings/cheat-sheet CSV export into a normalized
list of player dicts.

FantasyPros' export column names have shifted over the years (and differ
between the free consensus rankings export and the paid "My Cheat Sheet" /
Draft Wizard export), so this doesn't hard-code exact header text. Instead
it normalizes whatever headers are present and matches them against known
aliases. If a required field can't be found, it fails loudly with the
headers it did see, rather than silently producing empty columns.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field

# Header aliases, normalized (lowercase, non-alphanumeric stripped) -> field name.
_HEADER_ALIASES: dict[str, list[str]] = {
    "rank": ["rk", "rank", "overallrank", "ecrrank", "overall"],
    "tier": ["tier", "tiers"],
    "player": ["playername", "player", "name"],
    "team": ["team", "tm"],
    "position": ["pos", "position"],
    "bye": ["byeweek", "bye"],
    "adp": ["adp", "avgdraftposition", "averagedraftposition"],
    "points": ["fpts", "fantasypoints", "projpts", "projectedpoints", "pts"],
}

_REQUIRED = ["player", "position"]


def _normalize_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", h.strip().lower())


def _build_header_map(fieldnames: list[str]) -> dict[str, str]:
    """Map our internal field name -> the actual CSV column name present."""
    normalized = {_normalize_header(h): h for h in fieldnames}
    resolved: dict[str, str] = {}
    for field_name, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                resolved[field_name] = normalized[alias]
                break
    missing_required = [f for f in _REQUIRED if f not in resolved]
    if missing_required:
        raise ValueError(
            f"Couldn't find required column(s) {missing_required} in CSV headers "
            f"{fieldnames!r}. If FantasyPros changed their export format, add the "
            f"new header text to _HEADER_ALIASES in ingest.py."
        )
    return resolved


@dataclass
class Player:
    rank: int
    tier: int
    player: str
    team: str
    position: str  # normalized: QB/RB/WR/TE/K/DST, digits stripped
    bye: int | None = None
    adp: float | None = None
    points: float | None = None
    extra: dict = field(default_factory=dict)


_POS_RE = re.compile(r"[A-Za-z/]+")


def _normalize_position(raw: str) -> str:
    """'RB1' -> 'RB', 'D/ST' -> 'DST', 'PK' -> 'K'."""
    match = _POS_RE.match(raw.strip())
    pos = (match.group(0) if match else raw).upper().replace("/", "")
    if pos in ("DST", "DEF", "DEFENSE"):
        return "DST"
    if pos in ("PK",):
        return "K"
    return pos


def _to_int(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _to_float(value: str) -> float | None:
    value = (value or "").strip().replace(",", "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_cheatsheet(csv_path: str) -> list[Player]:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"{csv_path} has no header row")
        header_map = _build_header_map(list(reader.fieldnames))

        players: list[Player] = []
        for i, row in enumerate(reader, start=1):
            player_name = (row.get(header_map["player"]) or "").strip()
            if not player_name:
                continue  # skip blank trailing rows, common in these exports

            rank = _to_int(row.get(header_map.get("rank", ""), "")) or i
            tier = _to_int(row.get(header_map.get("tier", ""), "")) or 1
            position = _normalize_position(row.get(header_map["position"], ""))

            known_cols = set(header_map.values())
            extra = {k: v for k, v in row.items() if k not in known_cols}

            players.append(
                Player(
                    rank=rank,
                    tier=tier,
                    player=player_name,
                    team=(row.get(header_map.get("team", ""), "") or "").strip(),
                    position=position,
                    bye=_to_int(row.get(header_map.get("bye", ""), "")),
                    adp=_to_float(row.get(header_map.get("adp", ""), "")),
                    points=_to_float(row.get(header_map.get("points", ""), "")),
                    extra=extra,
                )
            )

    players.sort(key=lambda p: p.rank)
    return players
