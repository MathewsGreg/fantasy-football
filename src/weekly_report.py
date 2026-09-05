"""Generates the public weekly report: top waiver add/drop moves (with
rationale) up front, then start/sit suggestions (diffed against your
actual current ESPN lineup), then ranked waiver-wire targets grouped by
positional need. Writes docs/index.html for GitHub Pages to serve.

Deliberately doesn't publish FantasyPros' rankings table wholesale — only
your own derived roster/lineup/waiver analysis, computed from your real
ESPN league data, annotated with FantasyPros' weekly rank/grade/projection
per matched player as a second opinion (data/weekly/*.csv, if present).
See README's Phase 3 section.

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
from fp_blend import load_blend
from lineup import RosterPlayer, suggest_lineup, HARD_EXCLUDE_STATUSES

ROOT = Path(__file__).resolve().parent.parent


HEALTHY_STATUSES = {"", "ACTIVE", "NORMAL"}  # ESPN reports a healthy D/ST as
# 'NORMAL' rather than 'ACTIVE' or blank - confirmed against a real league
# (a healthy team defense showed up as "[NORMAL]"), so both count as fine.


def box_player_to_roster_player(bp) -> RosterPlayer:
    raw_status = bp.injuryStatus or ""
    if getattr(bp, "on_bye_week", False):
        status = "BYE"
    elif raw_status in HEALTHY_STATUSES:
        status = ""
    else:
        status = raw_status
    return RosterPlayer(
        player_id=str(bp.playerId),
        name=bp.name,
        position=normalize_position(bp.position),
        pro_team=bp.proTeam,
        injury_status=status,
        projected_points=bp.projected_points,
        current_slot=normalize_slot(bp.slot_position),
        percent_owned=getattr(bp, "percent_owned", None),
        # eligibleSlots already reflects THIS league's IR-slot rules (some
        # leagues require actual NFL injured reserve, others allow a plain
        # 'Out' designation, etc.) - ESPN's computed it for us, we just read it.
        ir_eligible="IR" in getattr(bp, "eligibleSlots", []),
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


def backfill_percent_owned(league, roster: list[RosterPlayer]) -> None:
    """box_scores() doesn't carry ownership data - confirmed against a real
    league, every roster player came back with percent_owned == -1 (the
    library's sentinel for 'ownership field missing from this API
    response'), which made every early waiver-move recommendation compare
    real free agents against fake near-zero values. player_info() hits a
    different view (kona_playercard) that does include it. Mutates roster
    in place; leaves percent_owned alone (as whatever box_scores gave it -
    almost certainly still -1) for any player this lookup can't resolve,
    rather than fabricating a number."""
    ids = [int(p.player_id) for p in roster]
    if not ids:
        return
    result = league.player_info(playerId=ids)
    if result is None:
        return
    players = result if isinstance(result, list) else [result]
    owned_by_id = {str(p.playerId): p.percent_owned for p in players if getattr(p, "percent_owned", None) is not None}
    for p in roster:
        owned = owned_by_id.get(p.player_id)
        if owned is not None and owned >= 0:
            p.percent_owned = owned


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


# espn_api's free_agents(position=...) matches against its own POSITION_MAP
# keys, which use ESPN's raw labels ('D/ST', not our normalized 'DST') -
# confirmed against a real league: passing 'DST' silently matched nothing,
# the slot filter fell through, and the "DST" group came back full of
# whatever's highest-owned overall (mostly WRs) instead of actual defenses.
ESPN_FREE_AGENT_POSITION = {"DST": "D/ST"}


# How deep to look per position: RB/WR are scarce and swing seasons, so we
# look deeper (including hurt/IR stashes worth grabbing for later); QB/TE/K/DST
# are thin and mostly interchangeable past the top few, so a short list is
# plenty and keeps the report from being cluttered with noise.
DEFAULT_WAIVER_DEPTH = {"QB": 5, "RB": 10, "WR": 10, "TE": 5, "K": 5, "DST": 5}


def rank_waiver_targets(league, need: dict, depth: dict = DEFAULT_WAIVER_DEPTH):
    positions = ["QB", "RB", "WR", "TE", "K", "DST"]
    # Positions you're short on first, then ok, then full - a real
    # grouping (need), not a fake single cross-position score.
    order = sorted(positions, key=lambda p: {"short": 0, "ok": 1, "full": 2}.get(need.get(p), 1))

    targets = {}
    for pos in order:
        espn_pos = ESPN_FREE_AGENT_POSITION.get(pos, pos)
        # Ranked by percent_owned - the wider fantasy market's read of
        # season-long value - not this week's projection, so an elite
        # player who's OUT/IR this week still surfaces as a stash target
        # rather than getting buried under healthy scrubs.
        candidates = league.free_agents(week=league.current_week, size=200, position=espn_pos)
        candidates.sort(key=lambda p: -(p.percent_owned or 0))
        targets[pos] = candidates[:depth.get(pos, 8)]
    return order, targets


# Minimum ownership-percentage gap between a free agent and your weakest
# same-position bench player before we bother suggesting the swap - keeps
# this list to moves that are actually worth the trouble, not noise from a
# 2-point ownership difference.
MIN_OWNERSHIP_GAP = 5.0


def top_waiver_moves(lineup_result, waiver_order, waiver_targets, max_moves: int = 5):
    """Best add/drop pairings: for each position, compare the top-owned
    available free agent against your weakest BENCH player at that same
    position (never a starter) by percent_owned - our season-value proxy.
    Deliberately doesn't require the free agent to be healthy *this week*:
    a hurt/IR player who's still clearly the better season-long asset than
    what you'd drop is exactly the stash-worthy move the ownership-based
    ranking is meant to surface."""
    bench_by_pos: dict[str, list] = {}
    for p in lineup_result.bench:
        bench_by_pos.setdefault(p.position, []).append(p)

    moves = []
    for pos in waiver_order:
        bench_list = bench_by_pos.get(pos)
        if not bench_list:
            continue  # nothing droppable at this position - nothing to suggest
        weakest = min(bench_list, key=lambda p: p.percent_owned if p.percent_owned is not None else -1)
        weakest_owned = weakest.percent_owned
        if weakest_owned is None or weakest_owned < 0:
            continue  # ownership never resolved for this player - don't guess

        best_fa = None
        for fa in waiver_targets.get(pos, []):
            fa_owned = fa.percent_owned or 0
            if fa_owned - weakest_owned >= MIN_OWNERSHIP_GAP:
                best_fa = fa
                break  # list is already sorted by ownership - first hit wins
        if best_fa is not None:
            moves.append({
                "pos": pos, "add": best_fa, "drop": weakest,
                "gap": (best_fa.percent_owned or 0) - weakest_owned,
            })

    moves.sort(key=lambda m: -m["gap"])
    return moves[:max_moves]


def fp_note(name: str, position: str, team: str, blend) -> str:
    """'RB7 (A, 15.9 pts)' from FantasyPros' weekly rankings - position
    rank, their own start/sit grade, and their projection - or '' if
    there's no blend loaded or this player isn't in it (e.g. that
    position's file wasn't downloaded, or he wasn't ranked)."""
    if blend is None:
        return ""
    fp_player = blend.lookup(name, position, team)
    if fp_player is None:
        return ""
    extras = []
    if fp_player.grade:
        extras.append(fp_player.grade)
    if fp_player.proj_fpts is not None:
        extras.append(f"{fp_player.proj_fpts:.1f} pts")
    suffix = f" ({', '.join(extras)})" if extras else ""
    return f"{position}{fp_player.rank}{suffix}"


def move_rationale(move: dict, blend=None) -> str:
    fa, drop, pos = move["add"], move["drop"], move["pos"]
    fa_status = "" if (fa.injuryStatus or "") in HEALTHY_STATUSES else fa.injuryStatus
    fa_owned = fa.percent_owned or 0
    drop_owned = drop.percent_owned or 0

    if fa_status in ("OUT", "INJURY_RESERVE"):
        timing = f"won't help this week ({fa_status.replace('_', ' ').title()}), but is"
    elif fa_status:
        timing = f"is {fa_status.title()} but could still help this week, and is"
    else:
        timing = "can help as soon as this week, and is"

    fp_bits = []
    fa_fp = fp_note(fa.name, pos, getattr(fa, "proTeam", ""), blend)
    if fa_fp:
        fp_bits.append(f"{fa.name} {fa_fp}")
    drop_fp = fp_note(drop.name, pos, drop.pro_team, blend)
    if drop_fp:
        fp_bits.append(f"{drop.name} {drop_fp}")
    fp_suffix = f" (FantasyPros: {'; '.join(fp_bits)}.)" if fp_bits else ""

    if drop.ir_eligible:
        # Your league's own IR rules already qualify this player - stashing
        # him there frees the roster spot for free, so there's no actual
        # trade-off to name here, unlike a real drop. Say plainly when he's
        # NOT actually injured (some leagues allow any rostered player into
        # IR) rather than papering over it with a vague word - confirmed
        # against a real league where an IR-eligible player had no injury
        # designation at all, and a generic "is eligible" reads as if he's
        # hurt when he isn't.
        if drop.injury_status:
            drop_clause = f"is {drop.injury_status.replace('_', ' ').title()} and IR-eligible in this league"
        else:
            drop_clause = ("isn't actually injured, but your league's IR-slot rules allow "
                            "any rostered player there anyway")
        if fa_status in ("OUT", "INJURY_RESERVE"):
            fa_clause = f"another season-long stash — he won't play this week ({fa_status.replace('_', ' ').title()}) either"
        elif fa_status:
            fa_clause = f"{fa_status.title()} but could still help this week"
        else:
            fa_clause = "can help as soon as this week"
        return (
            f"Add {fa.name} ({pos}, {fa_owned:.0f}% owned) — {fa_clause}. "
            f"{drop.name} ({drop_owned:.0f}% owned) {drop_clause}, so stash "
            f"him on IR instead of dropping him; that opens the roster spot "
            f"for {fa.name} at no cost.{fp_suffix}"
        )

    return (
        f"Add {fa.name} ({pos}, {fa_owned:.0f}% owned), drop {drop.name} "
        f"({drop_owned:.0f}% owned) — {timing} the clearly better season-long "
        f"asset at {pos}.{fp_suffix}"
    )


def render_html(league_name, me, week, lineup_result, opponent, my_proj, opp_proj, need, waiver_order, waiver_targets, top_moves, blend=None) -> str:
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
                "status": "" if (p.injuryStatus or "") in HEALTHY_STATUSES else p.injuryStatus,
                "fp": fp_note(p.name, pos, p.proTeam, blend),
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
        "fp_loaded": blend is not None,
        "fp_stale_days": round(blend.age_days) if (blend is not None and blend.stale) else None,
        "top_moves": [move_rationale(m, blend) for m in top_moves],
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

    blend = load_blend()
    if blend is None:
        print("No data/weekly/*.csv found - running without the FantasyPros "
              "second opinion (see README's Phase 3 section to add one).")
    elif blend.stale:
        print(f"WARNING: your oldest data/weekly/*.csv file is {blend.age_days:.0f} days old - "
              f"consider re-exporting from FantasyPros (their own refresh cycle is weekly).")

    league = get_league()
    me = find_team(league, my_team_name)
    week = league.current_week

    lineup_bp, opponent, my_proj, opp_proj = find_my_lineup(league, me)
    roster = [box_player_to_roster_player(bp) for bp in lineup_bp]
    backfill_percent_owned(league, roster)
    lineup_result = suggest_lineup(roster, config["roster_slots"], config["flex_eligible"])

    need = positional_need(roster, config["my_roster_targets"])
    waiver_order, waiver_targets = rank_waiver_targets(league, need)
    top_moves = top_waiver_moves(lineup_result, waiver_order, waiver_targets)

    html = render_html(
        league.settings.name, me, week, lineup_result, opponent, my_proj, opp_proj,
        need, waiver_order, waiver_targets, top_moves, blend,
    )

    out_dir = ROOT / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html)
    print(f"Wrote {out_path} (week {week}, {len(roster)} roster players, "
          f"{sum(len(v) for v in waiver_targets.values())} waiver candidates)")


if __name__ == "__main__":
    main()
