"""Generates the public weekly report: top waiver add/drop moves (with
rationale) up front, then start/sit suggestions (diffed against your
actual current ESPN lineup), then ranked waiver-wire targets grouped by
positional need. Writes docs/index.html for GitHub Pages to serve.

FantasyPros' weekly rank (data/weekly/*.csv) is the authoritative source
for lineup order and waiver targets — it decides who starts and which
free agents are worth looking at. Live ESPN league data (roster,
injury/bye status, matchup, percent_owned, next-game projection) supplies
everything FantasyPros' export doesn't — who's actually eligible, who's
actually a free agent right now — and is shown alongside each pick as
commentary, not as the ranking authority. If FantasyPros doesn't rank a
player (or data/weekly/ is empty entirely), that player just isn't
ranked; the report says so rather than quietly falling back to ESPN's
numbers as if they were equivalent. See README's Phase 3 section.

Run via scripts/weekly_refresh.ps1 (Task Scheduler, 3x/week). Every run
recomputes both sections regardless of which day it is.

Every run also diffs against snapshot.py's saved numbers from the
previous run, so each FantasyPros rank / ESPN ownership number shows how
it's moved since last time (see attach_rank_moves()) - a move is a signal
something happened (injury, role change, beat-writer report) worth going
and checking the news for. Also flags, per position, if the FantasyPros
source file is literally unchanged since last run (see
snapshot.stale_positions()) - a "forgot to grab this morning's export"
check, distinct from fp_blend.py's STALE_AFTER_DAYS age threshold.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from espn_client import get_league, find_team
from espn_normalize import normalize_position, normalize_slot
from fp_blend import load_blend
import snapshot as snap
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


def attach_fp_ranks(roster: list[RosterPlayer], blend) -> None:
    """FantasyPros' weekly position rank is the authoritative signal for
    lineup order (see module docstring) - mutates roster in place,
    attaching each player's FantasyPros rank/grade/projection where
    FantasyPros ranks him this week. Leaves fp_rank as None for anyone
    FantasyPros doesn't rank (no CSVs loaded at all, or genuinely absent
    from that position's export, e.g. a deep bench stash) rather than
    guessing - suggest_lineup() falls back to ESPN's projection only
    among that unranked subset, never to override a rank that exists."""
    if blend is None:
        return
    for p in roster:
        fp = blend.lookup(p.name, p.position, p.pro_team)
        if fp is not None:
            p.fp_rank = fp.rank
            p.fp_grade = fp.grade
            p.fp_proj = fp.proj_fpts


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


def rank_waiver_targets(league, need: dict, blend, depth: dict = DEFAULT_WAIVER_DEPTH):
    positions = ["QB", "RB", "WR", "TE", "K", "DST"]
    # Positions you're short on first, then ok, then full - a real
    # grouping (need), not a fake single cross-position score.
    order = sorted(positions, key=lambda p: {"short": 0, "ok": 1, "full": 2}.get(need.get(p), 1))

    targets: dict[str, list] = {}
    for pos in order:
        if blend is None:
            targets[pos] = []  # FantasyPros is the authoritative source now
            # and there's no data loaded at all this week - nothing to rank.
            continue
        espn_pos = ESPN_FREE_AGENT_POSITION.get(pos, pos)
        candidates = league.free_agents(week=league.current_week, size=200, position=espn_pos)
        # Ranked by FantasyPros' own weekly position rank - the authoritative
        # order now. A free agent FantasyPros doesn't rank this week is
        # excluded outright (not shown lower down) rather than falling back
        # to ESPN's percent_owned, which used to be the ranking signal here.
        ranked = []
        for fa in candidates:
            fp = blend.lookup(fa.name, pos, getattr(fa, "proTeam", ""))
            if fp is None:
                continue
            fa.fp_rank, fa.fp_grade, fa.fp_proj = fp.rank, fp.grade, fp.proj_fpts
            ranked.append(fa)
        ranked.sort(key=lambda p: p.fp_rank)
        targets[pos] = ranked[:depth.get(pos, 8)]
    return order, targets


def _snapshot_id(p) -> str:
    # RosterPlayer uses player_id (str, from ESPN's playerId); waiver-target
    # Player objects use ESPN's own playerId directly - both same underlying
    # ESPN ID, just different attribute names on the two object types.
    return str(getattr(p, "playerId", None) if hasattr(p, "playerId") else p.player_id)


def attach_rank_moves(roster: list[RosterPlayer], waiver_targets: dict, old_snapshot: dict) -> dict:
    """Attaches fp_move/owned_move (see snapshot.rank_move/ownership_move)
    to every roster and waiver-target player, comparing this run's
    FantasyPros rank and ESPN percent_owned against old_snapshot (last
    run's saved numbers) - a rank/ownership move is the signal that
    something happened (injury, role change, beat-writer report) worth
    going and checking the news for. Mutates the player objects in place
    rather than threading deltas through render_html separately, matching
    how attach_fp_ranks()/rank_waiver_targets() already attach FantasyPros
    data directly onto these objects. Returns this run's snapshot, to be
    saved (by main(), only after a successful run) as next run's
    old_snapshot."""
    new_snapshot: dict = {}

    def track(p, percent_owned) -> None:
        pid = _snapshot_id(p)
        old = old_snapshot.get(pid)
        p.fp_move = snap.rank_move(old, p.fp_rank)
        p.owned_move = snap.ownership_move(old, percent_owned)
        new_snapshot[pid] = snap.entry(p.fp_rank, percent_owned)

    for p in roster:
        track(p, p.percent_owned)
    for targets in waiver_targets.values():
        for fa in targets:
            track(fa, getattr(fa, "percent_owned", None))

    return new_snapshot


# FantasyPros position-rank spots the free agent must beat your weakest
# ranked bench player by before we bother suggesting the swap - same
# "worth the trouble, not noise" reasoning the old ownership-gap threshold
# (formerly MIN_OWNERSHIP_GAP) used, just against FantasyPros' rank now
# that it's the authoritative source instead of ESPN's percent_owned. A
# judgment call - revisit if the list feels too eager or too quiet.
MIN_RANK_IMPROVEMENT = 5


def top_waiver_moves(lineup_result, waiver_order, waiver_targets, max_moves: int = 5):
    """Best add/drop pairings: for each position, compare the top
    FantasyPros-ranked available free agent against your weakest
    FantasyPros-ranked BENCH player at that same position (never a
    starter). Bench players FantasyPros doesn't rank at all this week are
    skipped as drop candidates rather than assumed droppable - don't
    guess. Deliberately doesn't require the free agent to be healthy
    *this week*: a hurt/IR player FantasyPros still ranks well ahead of
    your bench guy is exactly the stash-worthy move this is meant to
    surface; the rationale says so explicitly either way."""
    bench_by_pos: dict[str, list] = {}
    for p in lineup_result.bench:
        bench_by_pos.setdefault(p.position, []).append(p)

    moves = []
    for pos in waiver_order:
        bench_list = [p for p in bench_by_pos.get(pos, []) if p.fp_rank is not None]
        if not bench_list:
            continue  # nothing FantasyPros ranks on your bench at this position - don't guess
        weakest = max(bench_list, key=lambda p: p.fp_rank)  # highest rank number = worst

        best_fa = None
        for fa in waiver_targets.get(pos, []):  # already FantasyPros-rank-sorted, best first
            if weakest.fp_rank - fa.fp_rank >= MIN_RANK_IMPROVEMENT:
                best_fa = fa
                break  # list is already sorted by rank - first hit wins
        if best_fa is not None:
            moves.append({
                "pos": pos, "add": best_fa, "drop": weakest,
                "gap": weakest.fp_rank - best_fa.fp_rank,
            })

    moves.sort(key=lambda m: -m["gap"])
    return moves[:max_moves]


def move_rationale(move: dict) -> str:
    fa, drop, pos = move["add"], move["drop"], move["pos"]
    fa_status = "" if (fa.injuryStatus or "") in HEALTHY_STATUSES else fa.injuryStatus

    fa_rank_bits = [f"{pos}{fa.fp_rank}"]
    if getattr(fa, "fp_grade", ""):
        fa_rank_bits.append(fa.fp_grade)
    fa_rank_txt = ", ".join(fa_rank_bits)
    drop_rank_txt = f"{pos}{drop.fp_rank}"

    if fa_status in ("OUT", "INJURY_RESERVE"):
        timing = f"won't help this week ({fa_status.replace('_', ' ').title()}), but is"
    elif fa_status:
        timing = f"is {fa_status.title()} but could still help this week, and is"
    else:
        timing = "can help as soon as this week, and is"

    # ESPN's ownership is commentary now, not the authority behind the
    # move - shown alongside FantasyPros' rank rather than driving it.
    espn_bits = []
    fa_owned = getattr(fa, "percent_owned", None)
    if fa_owned is not None and fa_owned >= 0:
        espn_bits.append(f"{fa.name} {fa_owned:.0f}% owned")
    if drop.percent_owned is not None and drop.percent_owned >= 0:
        espn_bits.append(f"{drop.name} {drop.percent_owned:.0f}% owned")
    espn_suffix = f" (ESPN: {'; '.join(espn_bits)}.)" if espn_bits else ""

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
            f"Add {fa.name} (FantasyPros {fa_rank_txt}) — {fa_clause}. "
            f"{drop.name} (FantasyPros {drop_rank_txt}) {drop_clause}, so "
            f"stash him on IR instead of dropping him; that opens the roster "
            f"spot for {fa.name} at no cost.{espn_suffix}"
        )

    return (
        f"Add {fa.name} (FantasyPros {fa_rank_txt}), drop {drop.name} "
        f"(FantasyPros {drop_rank_txt}) — {timing} the clearly better "
        f"FantasyPros-ranked option at {pos} this week.{espn_suffix}"
    )


def render_html(league_name, me, week, lineup_result, opponent, my_proj, opp_proj, need, waiver_order, waiver_targets, top_moves, blend=None, fp_unchanged_positions=None) -> str:
    template = (Path(__file__).parent / "report_template.html").read_text()

    def player_row(p):
        fp = f"{p.position}{p.fp_rank}" if p.fp_rank is not None else "—"
        espn_proj = f"{p.projected_points:.1f}" if p.projected_points is not None else "—"
        return {
            "name": p.name, "pos": p.position, "team": p.pro_team,
            "fp": fp, "fp_grade": p.fp_grade or "", "fp_move": p.fp_move,
            "espn_proj": espn_proj, "status": p.injury_status,
        }

    starters = [
        {"slot": slot.slot_name, **(player_row(slot.player) if slot.player else {"name": "(empty)", "pos": "", "team": "", "fp": "", "fp_grade": "", "fp_move": None, "espn_proj": "", "status": ""})}
        for slot in lineup_result.starters
    ]
    bench = [player_row(p) for p in lineup_result.bench]

    waivers = {
        pos: [
            {
                "name": p.name, "team": p.proTeam,
                "fp": f"{pos}{p.fp_rank}",
                "fp_grade": getattr(p, "fp_grade", "") or "",
                "fp_move": getattr(p, "fp_move", None),
                "fp_proj": f"{p.fp_proj:.1f}" if getattr(p, "fp_proj", None) is not None else "—",
                "espn_owned": f"{p.percent_owned:.0f}%" if (getattr(p, "percent_owned", None) is not None and p.percent_owned >= 0) else "—",
                "owned_move": getattr(p, "owned_move", None),
                "espn_proj": f"{p.projected_points:.1f}" if getattr(p, "projected_points", None) else "—",
                "status": "" if (p.injuryStatus or "") in HEALTHY_STATUSES else p.injuryStatus,
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
        "fp_as_of": blend.as_of_str if blend is not None else None,
        "fp_stale": blend.stale if blend is not None else None,
        "fp_stale_days": round(blend.age_days) if blend is not None else None,
        "fp_unchanged_positions": fp_unchanged_positions or [],
        "top_moves": [move_rationale(m) for m in top_moves],
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
        print("No data/weekly/*.csv found - FantasyPros is the authoritative "
              "source for lineup order and waiver targets now, so neither can "
              "be ranked until you add weekly exports (see README's Phase 3 "
              "section).")
    elif blend.stale:
        print(f"WARNING: your oldest currently-used FantasyPros position file is "
              f"{blend.age_days:.0f} days old (as of {blend.as_of_str}) - consider "
              f"re-exporting from FantasyPros (their own refresh cycle is weekly). "
              f"Still using it as the authoritative source rather than falling "
              f"back to ESPN - the report publishes this date so you know how "
              f"fresh it is. Old weeks already archived in data/weekly/ don't "
              f"count against this, only whichever week is newest per position.")

    league = get_league()
    me = find_team(league, my_team_name)
    week = league.current_week

    lineup_bp, opponent, my_proj, opp_proj = find_my_lineup(league, me)
    roster = [box_player_to_roster_player(bp) for bp in lineup_bp]
    backfill_percent_owned(league, roster)
    attach_fp_ranks(roster, blend)
    lineup_result = suggest_lineup(roster, config["roster_slots"], config["flex_eligible"])

    need = positional_need(roster, config["my_roster_targets"])
    waiver_order, waiver_targets = rank_waiver_targets(league, need, blend)
    top_moves = top_waiver_moves(lineup_result, waiver_order, waiver_targets)

    old_snapshot = snap.load_snapshot()
    new_player_snapshot = attach_rank_moves(roster, waiver_targets, old_snapshot["players"])

    new_fp_sources = blend.sources if blend is not None else {}
    # Distinct from blend.stale (an age threshold): this catches "the
    # export I'm using is the exact same file as last run's" even when
    # it isn't old enough to trip STALE_AFTER_DAYS - the intended workflow
    # is grabbing fresh FantasyPros files each Tue/Thu/Sun morning before
    # the scheduled run, and this is what flags a forgotten morning.
    fp_unchanged_positions = snap.stale_positions(old_snapshot["fp_sources"], new_fp_sources)
    if fp_unchanged_positions:
        print(f"NOTE: FantasyPros source file unchanged since last report for: "
              f"{', '.join(fp_unchanged_positions)} - did you forget to grab "
              f"fresh exports for those positions this morning?")

    html = render_html(
        league.settings.name, me, week, lineup_result, opponent, my_proj, opp_proj,
        need, waiver_order, waiver_targets, top_moves, blend, fp_unchanged_positions,
    )

    out_dir = ROOT / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html)
    # Only save the new snapshot once the report itself has written
    # successfully - a failed run shouldn't overwrite good history that
    # the next run needs to diff against.
    snap.save_snapshot(new_player_snapshot, new_fp_sources)
    print(f"Wrote {out_path} (week {week}, {len(roster)} roster players, "
          f"{sum(len(v) for v in waiver_targets.values())} waiver candidates)")


if __name__ == "__main__":
    main()
