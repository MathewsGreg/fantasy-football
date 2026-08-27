"""Value-based-drafting math: given a league's roster construction, figure
out how many players at each position are actually "startable" across the
league, and rank each player against that replacement level.

If the CSV carries projected points (a premium FantasyPros projections
export, not the free consensus rankings), value is points above the
replacement-level player at the same position — textbook VBD. Otherwise
(the common case: just rank/tier), value falls back to "cushion above
replacement" measured in rank slots, which is a weaker signal but still
useful for spotting when a position is about to run dry.
"""

from __future__ import annotations

from dataclasses import asdict

from ingest import Player


def effective_starters(config: dict) -> dict[str, int]:
    """How many players at each position are startable league-wide, once
    FLEX slots are allocated proportionally across flex-eligible positions."""
    teams = config["teams"]
    slots = config["roster_slots"]
    flex_eligible = config["flex_eligible"]
    flex_weights = config["flex_split_weights"]

    starters = {
        pos: count * teams
        for pos, count in slots.items()
        if pos != "FLEX"
    }
    # Positions with no dedicated slot (e.g. a superflex-only position)
    # still need an entry so flex allocation below doesn't KeyError.
    for pos in flex_eligible:
        starters.setdefault(pos, 0)

    flex_total = slots.get("FLEX", 0) * teams
    if flex_total and flex_eligible:
        raw = {pos: flex_total * flex_weights.get(pos, 0) for pos in flex_eligible}
        allocated = {pos: int(raw[pos]) for pos in flex_eligible}
        remainder = flex_total - sum(allocated.values())
        # Give leftover slots (from rounding) to the position with the
        # largest fractional remainder, breaking ties by weight.
        fractions = sorted(
            flex_eligible,
            key=lambda p: (raw[p] - int(raw[p]), flex_weights.get(p, 0)),
            reverse=True,
        )
        for pos in fractions[:remainder]:
            allocated[pos] += 1
        for pos, n in allocated.items():
            starters[pos] = starters.get(pos, 0) + n

    return starters


def annotate(players: list[Player], config: dict) -> list[dict]:
    """Return plain dicts (JSON-ready) with position_rank and
    value_over_replacement added."""
    starters = effective_starters(config)

    by_position: dict[str, list[Player]] = {}
    for p in players:
        by_position.setdefault(p.position, []).append(p)

    replacement_points: dict[str, float | None] = {}
    for pos, plist in by_position.items():
        plist.sort(key=lambda p: p.rank)
        cutoff = starters.get(pos, 0)
        if 0 < cutoff <= len(plist) and plist[cutoff - 1].points is not None:
            replacement_points[pos] = plist[cutoff - 1].points
        else:
            replacement_points[pos] = None

    out = []
    for pos, plist in by_position.items():
        replacement = replacement_points[pos]
        for i, p in enumerate(plist, start=1):
            d = asdict(p)
            d["position_rank"] = i
            d["effective_starters"] = starters.get(pos, 0)
            if replacement is not None and p.points is not None:
                d["value_over_replacement"] = round(p.points - replacement, 1)
                d["value_basis"] = "points"
            else:
                d["value_over_replacement"] = starters.get(pos, 0) - i
                d["value_basis"] = "rank_cushion"
            out.append(d)

    out.sort(key=lambda d: d["rank"])
    return out
