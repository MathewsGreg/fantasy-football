"""Generate placeholder sample data shaped like a FantasyPros half-PPR
cheat-sheet export, for testing the ingest/VBD pipeline before you have a
real export. Player names are obviously fake — do not use this for an
actual draft.

Usage: python make_sample_data.py > ../data/sample_cheatsheet.csv
"""

from __future__ import annotations

POSITION_COUNTS = [("QB", 15), ("RB", 45), ("WR", 50), ("TE", 15), ("K", 12), ("DST", 12)]


def main() -> None:
    rows = [("RK", "TIERS", "PLAYER NAME", "TEAM", "POS", "BYE WEEK", "ADP")]

    # Interleave positions roughly by typical ADP shape (RB/WR early and
    # often, QB/TE clustered a bit later, K/DST last) rather than blocking
    # them, so the sample exercises tier boundaries the same way a real
    # export would.
    pool = []
    for pos, n in POSITION_COUNTS:
        for i in range(1, n + 1):
            pool.append((pos, i))

    weight = {"RB": 3, "WR": 3, "QB": 1, "TE": 1}
    order = []
    counters = {pos: 0 for pos, _ in POSITION_COUNTS}
    remaining = dict(POSITION_COUNTS)
    skill_positions = [pos for pos in remaining if pos not in ("K", "DST")]
    while sum(remaining[pos] for pos in skill_positions) > 0:
        for pos in skill_positions:
            for _ in range(weight.get(pos, 1)):
                if remaining[pos] > 0:
                    counters[pos] += 1
                    order.append((pos, counters[pos]))
                    remaining[pos] -= 1
    # K/DST are typically drafted last, after every startable skill-position
    # player — append them at the end rather than interleaving.
    for pos in ("K", "DST"):
        while remaining[pos] > 0:
            counters[pos] += 1
            order.append((pos, counters[pos]))
            remaining[pos] -= 1

    for overall_rank, (pos, pos_rank) in enumerate(order, start=1):
        tier = (overall_rank - 1) // 8 + 1
        bye = 5 + (overall_rank % 10)
        adp = round(overall_rank * 1.0 + (overall_rank % 3) * 0.3, 1)
        name = f"Sample {pos} {pos_rank:02d}"
        team = f"T{(overall_rank % 32) + 1:02d}"
        rows.append((str(overall_rank), str(tier), name, team, pos, str(bye), str(adp)))

    for row in rows:
        print(",".join(row))


if __name__ == "__main__":
    main()
