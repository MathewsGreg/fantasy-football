"""Start/sit logic: given your current roster and the league's roster
shape, suggest a starting lineup by projected points and diff it against
whatever ESPN currently has you starting.

Deliberately doesn't try to be clever about matchups, weather, or
game script — it's a projection-ranking exercise, same VBD-adjacent
spirit as the draft board. Treat the diff as a prompt to go look at the
specific swap, not an instruction to blindly follow.
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
    projected_points: float | None
    current_slot: str  # ESPN's lineupSlot, e.g. 'RB', 'WR', 'BE', 'FLEX', 'IR'
    percent_owned: float | None = None  # league-wide ownership - our proxy for
    # season-long value, independent of this week's health/projection
    ir_eligible: bool = False  # ESPN's own read of whether THIS league's IR-slot
    # rules currently qualify this player - not something we compute ourselves

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
    # Unprojected players sort after projected ones, not at rank 0 - "no
    # data" shouldn't look worse than "projected for 0 points."
    has_projection = p.projected_points is not None
    return (not has_projection, -(p.projected_points or 0))


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
    flex_pool.sort(key=_sort_key)
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
            reason = "no healthy alternative" if not eligible else "higher projection than your current starter"
            result.changes.append(f"Start {p.name} ({slot.slot_name}) — currently benched, {reason}.")
        elif p.warn:
            result.changes.append(f"{p.name} is {p.injury_status.title()} — worth a game-time check before locking {slot.slot_name}.")
    for p in roster:
        if p.currently_starting and p.player_id not in suggested_starter_ids:
            if p.injury_status == "BYE":
                why = "on a bye this week"
            elif p.hard_excluded:
                why = f"is {p.injury_status.title()}"
            else:
                why = "projects behind your other options"
            result.changes.append(f"Bench {p.name} — {why}.")

    return result
