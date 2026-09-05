"""Generates the public weekly report: start/sit suggestions (diffed
against your actual current ESPN lineup) and ranked waiver-wire targets
grouped by positional need. Writes docs/fantasy/index.html for GitHub
Pages to serve alongside the MLB dashboard.

Deliberately doesn't publish FantasyPros' rankings table itself — only
your own derived roster/lineup/waiver analysis, computed from your real
ESPN league data. See README's Phase 3 section.

Run via scripts/weekly_refresh.ps1 (Task Scheduler, 3x/week). Every run
recomputes both sections regardless of which day it is.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from espn_client import get_league, find_team
from espn_normalize import normalize_position, normalize_slot
from lineup import RosterPlayer, suggest_lineup, HARD_EXCLUDE_STATUSES

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent


def box_player_to_roster_player(bp) -> RosterPlayer:
    status = "BYE" if getattr(bp, "on_bye_week", False) else (bp.injuryStatus or "")
    return RosterPlayer(
        player_id=str(bp.playerId),
        name=bp.name,
        position=normalize_position(bp.position),
        pro_team=bp.proTeam,
        injury_status=status,
        projected_points=bp.projected_points,
        current_slot=normalize_slot(bp.slot_position),
    )


def find_my_lineup(league, me):
    """This week's box score for my team, so we get real slot assignments,
    per-week projections, and opponent info rather than reconstructing it
    from raw roster data."""
    for matchup in league.box_scores(week=league.current_week):
        if getattr(matchup.home_team, "team_id", None) == me.team_id:
            return matchup.home_lineup, matchup.away_team, matchup.home_projected, matchup.away_projected
        if getattr(matchup.away_team, "team_id", None) == me.team_id:
            return matchup.away_lineup, matchup.home_team, matchup.away_projected, matchup.home_projected
    raise ValueError(f"No matchup found for {me.team_name} in week {league.current_week} (bye week?)")


def positional_need(roster: list[RosterPlayer], targets: dict) -> dict[str, str]:
    """'short' / 'ok' / 'full' per position, from current roster depth vs
    my_roster_targets. Informational grouping, not a hard cutoff."""
    counts: dict[str, int] = {}
    for p in roster:
        counts[p.position] = counts.get(p.position, 0) + 1
    need = {}
    for pos, target in targets.items():
        if pos == "FLEX":
            continue
        upper = target[1] if isinstance(target, list) else target
        lower = target[0] if isinstance(target, list) else target
        have = counts.get(pos, 0)
        if have < lower:
            need[pos] = "short"
        elif have < upper:
            need[pos] = "ok"
        else:
            need[pos] = "full"
    return need


def rank_waiver_targets(league, need: dict, size_per_position: int = 8):
    positions = ["QB", "RB", "WR", "TE", "K", "DST"]
    # Positions you're short on first, then ok, then full - a real
    # grouping (need), not a fake single cross-position score.
    order = sorted(positions, key=lambda p: {"short": 0, "ok": 1, "full": 2}.get(need.get(p), 1))

    targets = {}
    for pos in order:
        candidates = league.free_agents(week=league.current_week, size=200, position=pos)
        candidates.sort(key=lambda p: -(p.percent_owned or 0))
        targets[pos] = candidates[:size_per_position]
    return order, targets


def render_html(league_name, me, week, lineup_result, opponent, my_proj, opp_proj, need, waiver_order, waiver_targets) -> str:
    template = (Path(__file__).parent / "report_template.html").read_text()

    def player_row(p):
        status_html = f'<span class="tag warn">{p.injury_status}</span>' if p.injury_status else ""
        proj = f"{p.projected_points:.1f}" if p.projected_points is not None else "—"
        return {
            "name": p.name, "pos": p.position, "team": p.pro_team,
            "proj": proj, "status": p.injury_status,
        }

    starters = [
        {"slot": slot.slot_name, **(player_row(slot.player) if slot.player else {"name": "(empty)", "pos": "", "team": "", "proj": "", "status": ""})}
        for slot in lineup_result.starters
    ]
    bench = [player_row(p) for p in lineup_result.bench]

    waivers = {
        pos: [
            {
                "name": p.name, "team": p.proTeam,
                "owned": f"{p.percent_owned:.0f}%" if getattr(p, "percent_owned", None) is not None else "—",
                "proj": f"{p.projected_points:.1f}" if getattr(p, "projected_points", None) else "—",
                "status": "" if (p.injuryStatus or "") in ("ACTIVE", "") else p.injuryStatus,
            }
            for p in waiver_targets[pos]
        ]
        for pos in waiver_order
    }

    data = {
        "league_name": league_name,
        "team_name": me.team_name,
        "week": week,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "opponent": opponent.team_name if opponent else None,
        "my_projected": round(my_proj, 1) if my_proj else None,
        "opp_projected": round(opp_proj, 1) if opp_proj else None,
        "starters": starters,
        "bench": bench,
        "changes": lineup_result.changes,
        "need": need,
        "waiver_order": waiver_order,
        "waivers": waivers,
    }

    return template.replace("__REPORT_DATA_JSON__", json.dumps(data))


def main() -> None:
    config = json.loads((ROOT / "league_config.json").read_text())
    my_team_name = config["team_names"][config["my_team"] - 1]

    league = get_league()
    me = find_team(league, my_team_name)
    week = league.current_week

    lineup_bp, opponent, my_proj, opp_proj = find_my_lineup(league, me)
    roster = [box_player_to_roster_player(bp) for bp in lineup_bp]
    lineup_result = suggest_lineup(roster, config["roster_slots"], config["flex_eligible"])

    need = positional_need(roster, config["my_roster_targets"])
    waiver_order, waiver_targets = rank_waiver_targets(league, need)

    html = render_html(
        league.settings.name, me, week, lineup_result, opponent, my_proj, opp_proj,
        need, waiver_order, waiver_targets,
    )

    out_dir = REPO_ROOT / "docs" / "fantasy"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html)
    print(f"Wrote {out_path} (week {week}, {len(roster)} roster players, "
          f"{sum(len(v) for v in waiver_targets.values())} waiver candidates)")


if __name__ == "__main__":
    main()
