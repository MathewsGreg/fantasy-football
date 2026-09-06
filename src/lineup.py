"""Start/sit logic: given your current roster and the league's roster
shape, suggest a starting lineup by FantasyPros' weekly position rank
(the authoritative signal - see weekly_report.py's attach_fp_ranks) and
diff it against whatever ESPN currently has you starting. ESPN's own
next-game projection is used only to order the players FantasyPros
doesn't rank this week, never to override a FantasyPros rank that exists.

FLEX is the one place position rank can't be used directly: it compares
players across positions, and FantasyPros' rank scale isn't comparable
across positions (TE14 and WR15 aren't remotely the same quality of
player - TE only has a couple dozen fantasy-relevant options in a given
week). FLEX candidates are compared on FantasyPros' own point projection
instead, which is on the same scale for everyone - see
_cross_position_sort_key.

Deliberately doesn't try to be clever about matchups, weather, or
game script beyond what FantasyPros' own rank already bakes in. Treat
the diff as a prompt to go look at the specific swap, not an instruction
to blindly follow.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Can't play at all this week - never suggested as a starter. BYE isn't a
# real ESPN injury status; weekly_report.py sets it synthetically when a
# player's pro team has the week off.
HARD_EXCLUDE_STATUSES = {"OUT", "INJURY_RESERVE", "SUSPENSION", "BYE"}
# Might not play - kept eligible (sometimes these guys play), but flagged.
WARN_STATUSES = {"DOUBTFUL", "QUESTIONABLE"}

# ESPN lineupSlot strings that count as "currently benched" rather than starting.
BENCH_SLOTS = {"BE", "IR"}


@dataclass
class RosterPlayer:
    player_id: str
    name: str
    position: str  # QB/RB/WR/TE/K/DST
    pro_team: str
    injury_status: str  # '' / ACTIVE / QUESTIONABLE / DOUBTFUL / OUT / INJURY_RESERVE / ...
    projected_points: float | None  # ESPN's next-game projection - commentary
    # now, not the ranking authority (see fp_rank below)
    current_slot: str  # ESPN's lineupSlot, e.g. 'RB', 'WR', 'BE', 'FLEX', 'IR'
    percent_owned: float | None = None  # ESPN league-wide ownership - commentary
    # only; used to be the waiver-ranking authority, FantasyPros' rank is now
    ir_eligible: bool = False  # ESPN's own read of whether THIS league's IR-slot
    # rules currently qualify this player - not something we compute ourselves
    fp_rank: int | None = None  # FantasyPros' weekly position rank - the
    # authoritative signal for lineup order now. None means FantasyPros
    # doesn't rank this player this week (no CSVs loaded, or genuinely
    # absent from that position's export) - never guessed or backfilled.
    fp_grade: str = ""  # FantasyPros' own start/sit letter grade, if ranked
    fp_proj: float | None = None  # FantasyPros' own point projection, if ranked
    fp_move: dict | None = None  # {'text', 'dir', 'notable'} - how fp_rank
    # has moved since the last report run (see snapshot.rank_move()), or
    # None if there's nothing to compare. Attached by weekly_report.py,
    # not computed here - lineup.py doesn't know about run history.
    owned_move: dict | None = None  # same shape, for percent_owned
    # (see snapshot.ownership_move())

    @property
    def currently_starting(self) -> bool:
        return self.current_slot not in BENCH_SLOTS

    @property
    def hard_excluded(self) -> bool:
        return self.injury_status in HARD_EXCLUDE_STATUSES

    @property
    def warn(self) -> bool:
        return self.injury_status in WARN_STATUSES


@dataclass
class LineupSlot:
    slot_name: str  # 'QB', 'RB1', 'RB2', 'FLEX1', ...
    player: RosterPlayer | None


@dataclass
class LineupSuggestion:
    starters: list[LineupSlot] = field(default_factory=list)
    bench: list[RosterPlayer] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)


def _sort_key(p: RosterPlayer):
    # FantasyPros' own weekly position rank is the authoritative order for
    # comparing players at the SAME position - lower rank sorts first. Only
    # valid within one position: use _cross_position_sort_key for FLEX,
    # which compares players across positions. A player FantasyPros doesn't
    # rank this week (no CSVs loaded, or genuinely absent from that
    # position's export) sorts after every ranked player, never ahead of
    # one on the strength of ESPN's projection alone; among that unranked
    # group, ESPN's projection is used only as a last-resort tiebreaker so
    # the lineup still fills out sensibly. Unprojected players within that
    # group sort last of all, not at rank 0 - "no data" shouldn't look
    # worse than "projected for 0 points."
    has_fp_rank = p.fp_rank is not None
    has_projection = p.projected_points is not None
    return (not has_fp_rank, p.fp_rank if has_fp_rank else 0, not has_projection, -(p.projected_points or 0))


def _cross_position_sort_key(p: RosterPlayer):
    # FantasyPros' position rank is NOT comparable across positions - e.g.
    # TE only has ~25 fantasy-relevant players in a given week, so TE14 is
    # a mediocre streamer, while WR15 among ~100+ relevant WRs is a clear
    # must-start, even though 14 < 15. FLEX candidates come from multiple
    # positions at once, so cross-position comparison uses FantasyPros' own
    # point projection instead (comparable across positions, same reason
    # ESPN's projection served this role in the pre-FantasyPros-authoritative
    # design) - confirmed against a real week's data, where raw-rank
    # comparison had a low-end TE bumping a clearly-better WR out of FLEX.
    # Falls back to ESPN's projection only for players FantasyPros doesn't
    # project at all.
    has_fp_proj = p.fp_proj is not None
    has_projection = p.projected_points is not None
    return (not has_fp_proj, -(p.fp_proj or 0), not has_projection, -(p.projected_points or 0))


def suggest_lineup(roster: list[RosterPlayer], roster_slots: dict, flex_eligible: list[str]) -> LineupSuggestion:
    eligible = [p for p in roster if not p.hard_excluded]
    by_position: dict[str, list[RosterPlayer]] = {}
    for p in eligible:
        by_position.setdefault(p.position, []).append(p)
    for plist in by_position.values():
        plist.sort(key=_sort_key)

    result = LineupSuggestion()
    used_ids = set()

    dedicated_positions = [pos for pos in roster_slots if pos != "FLEX"]
    for pos in dedicated_positions:
        count = roster_slots[pos]
        pool = by_position.get(pos, [])
        for i in range(count):
            player = pool[i] if i < len(pool) else None
            if player:
                used_ids.add(player.player_id)
            slot_name = pos if count == 1 else f"{pos}{i + 1}"
            result.starters.append(LineupSlot(slot_name, player))

    flex_pool = [
        p for pos in flex_eligible
        for p in by_position.get(pos, [])
        if p.player_id not in used_ids
    ]
    flex_pool.sort(key=_cross_position_sort_key)
    flex_count = roster_slots.get("FLEX", 0)
    for i in range(flex_count):
        player = flex_pool[i] if i < len(flex_pool) else None
        if player:
            used_ids.add(player.player_id)
        slot_name = "FLEX" if flex_count == 1 else f"FLEX{i + 1}"
        result.starters.append(LineupSlot(slot_name, player))

    result.bench = [p for p in roster if p.player_id not in used_ids]

    # Diff against what ESPN currently has starting.
    suggested_starter_ids = {slot.player.player_id for slot in result.starters if slot.player}
    for slot in result.starters:
        p = slot.player
        if p is None:
            continue
        if not p.currently_starting:
            is_flex = slot.slot_name.startswith("FLEX")
            if not eligible:
                reason = "no healthy alternative"
            elif is_flex and p.fp_proj is not None:
                # FLEX compares across positions on FantasyPros' point
                # projection (see _cross_position_sort_key), not raw rank -
                # say so, since citing his position rank here would imply a
                # comparison that isn't actually how FLEX was decided.
                reason = f"FantasyPros projects him for {p.fp_proj:.1f} pts this week"
            elif p.fp_rank is not None:
                reason = f"FantasyPros ranks him {p.position}{p.fp_rank} this week"
            else:
                reason = "no FantasyPros rank this week — using ESPN's projection"
            result.changes.append(f"Start {p.name} ({slot.slot_name}) — currently benched, {reason}.")
        elif p.warn:
            result.changes.append(f"{p.name} is {p.injury_status.title()} — worth a game-time check before locking {slot.slot_name}.")
    for p in roster:
        if p.currently_starting and p.player_id not in suggested_starter_ids:
            if p.injury_status == "BYE":
                why = "on a bye this week"
            elif p.hard_excluded:
                why = f"is {p.injury_status.title()}"
            elif p.fp_rank is not None:
                # Include his own FantasyPros point projection alongside the
                # rank when available - rank alone isn't comparable across
                # positions (a FLEX bench reason citing only "TE9" or "WR15"
                # can't be sanity-checked against each other without it).
                proj_bit = f", {p.fp_proj:.1f} pts" if p.fp_proj is not None else ""
                why = f"ranked behind your other options by FantasyPros ({p.position}{p.fp_rank}{proj_bit})"
            else:
                why = "projects behind your other options (no FantasyPros rank this week)"
            result.changes.append(f"Bench {p.name} — {why}.")

    return result
