"""Thin wrapper around the unofficial `espn_api` library for read-only
access to our league: your roster, the actual free-agent pool, and
matchups. No write access is used or attempted anywhere in here (see
README.md for why: there's no documented, reliable write endpoint for
anything in ESPN's fantasy API, so this only ever reads).

Auth is your ESPN login session (espn_s2 / SWID cookies), not an API key —
treat it like a password. Loaded from a gitignored .env; see .env.example.
"""

from __future__ import annotations

import os
from pathlib import Path

from espn_api.football import League

ROOT = Path(__file__).resolve().parent.parent


def load_env(env_path: Path = ROOT / ".env") -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def get_league(year: int | None = None) -> League:
    load_env()
    league_id = os.environ.get("ESPN_LEAGUE_ID")
    espn_s2 = os.environ.get("ESPN_S2")
    swid = os.environ.get("ESPN_SWID")
    if not league_id:
        raise SystemExit(
            "ESPN_LEAGUE_ID not set. Copy .env.example to .env and fill in "
            "your league ID + cookies."
        )
    if not espn_s2 or not swid:
        raise SystemExit(
            "ESPN_S2 / ESPN_SWID not set (needed for a private league). "
            "Fill them in in .env — see .env.example for where to find "
            "them in your browser's cookies."
        )
    if year is None:
        import datetime
        # NFL season year rolls over in ESPN's numbering around March, well
        # before a new fantasy season would be configured, so "this
        # calendar year" is always right during football season.
        year = datetime.date.today().year

    return League(league_id=int(league_id), year=year, espn_s2=espn_s2, swid=swid)


def find_team(league: League, team_name: str):
    """Match by name rather than assuming ESPN's internal team_id lines up
    with our draft-order team numbering (it usually won't)."""
    target = team_name.strip().lower()
    for team in league.teams:
        if team.team_name.strip().lower() == target:
            return team
    available = ", ".join(t.team_name for t in league.teams)
    raise ValueError(f"No ESPN team named {team_name!r} found. Teams in this league: {available}")
