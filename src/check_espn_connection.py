"""Sanity check for the ESPN connection: prints your team's roster and a
handful of top free agents. Run this first, before trusting any waiver
tool built on top of espn_client.py.

Usage: python check_espn_connection.py
"""

from __future__ import annotations

import json
from pathlib import Path

from espn_client import get_league, find_team

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    config = json.loads((ROOT / "league_config.json").read_text())
    my_team_name = config["team_names"][config["my_team"] - 1]

    league = get_league()
    print(f"Connected to: {league.settings.name} ({len(league.teams)} teams)")

    me = find_team(league, my_team_name)
    print(f"\n{me.team_name} ({me.wins}-{me.losses}) roster:")
    for p in me.roster:
        status = f" [{p.injuryStatus}]" if getattr(p, "injuryStatus", "ACTIVE") not in ("ACTIVE", "NORMAL", "") else ""
        print(f"  {p.position:>4}  {p.name} ({p.proTeam}){status}")

    print("\nTop 15 free agents by ESPN's own ranking:")
    for p in league.free_agents(size=15):
        pct = getattr(p, "percent_owned", None)
        pct_txt = f", {pct:.0f}% owned" if pct is not None else ""
        print(f"  {p.position:>4}  {p.name} ({p.proTeam}){pct_txt}")


if __name__ == "__main__":
    main()
