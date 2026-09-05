# Fantasy Football Draft Board

A companion tool for a 10-team half-PPR league (QB, 2×RB, 2×WR, TE, FLEX,
K, DST) that turns a FantasyPros consensus-rankings export into a live
draft-day board: sortable/filterable player list, consensus tiers,
positional-scarcity countdown, and click-to-mark-drafted tracking with a
snake-draft clock. Runs entirely as one static HTML file — no server,
no account, no network dependency during the draft itself.

## Why not just use ESPN's own draft queue?

Short answer: reading your league's data back from ESPN (rosters, free
agents, injury status) is very doable through its unofficial API — that's
what phases 2/3 below use. *Writing* into ESPN's live pre-draft
queue/rankings isn't: there's no documented or reliably-available endpoint
for bulk-importing a custom order into it, only community reverse-engineering
of read endpoints. So this board is a second-screen companion you keep open
during ESPN's live draft, not something that pushes into ESPN's UI. If that
changes, worth revisiting — but nothing to depend on for Sunday.

## Phase 1: the draft board (this week)

### 1. Get your rankings

1. Log into [FantasyPros](https://www.fantasypros.com) (free account is fine).
2. Go to the half-PPR rankings / cheat sheet tool and set scoring to
   **Half-PPR**.
3. Export/download the CSV (labeled "Export to CSV" or, on the Cheat Sheet
   Creator, the download icon).
4. Save it as `fantasy-football/data/cheatsheet.csv` (gitignored — it's
   FantasyPros' content, not something to publish).

### 2. Build the board

```
cd fantasy-football/src
python3 build_board.py
```

This reads `league_config.json` (our roster settings) and
`data/cheatsheet.csv`, computes how many players at each position are
actually startable league-wide, and writes `site/draft_board.html`.

If `data/cheatsheet.csv` doesn't exist yet, it builds from
`data/sample_cheatsheet.csv` instead — clearly-labeled placeholder data
(fake names like "Sample RB 04") for testing the pipeline. **Don't draft
off the sample data** — the board itself flags it with a warning banner
so it's obvious if you forgot to swap in the real export.

### 3. Use it on draft day

Just open `site/draft_board.html` in a browser — double-click it, no
server needed. It works fully offline once loaded (only the Google Fonts
stylesheet needs network, and it falls back to system fonts without it).

- Click **Draft** on a player to mark them taken; the snake-draft clock
  (pick #, round, team on the clock) advances automatically. Set **My
  team** in the top bar so your own turn highlights.
- The position strip at the top counts down startable players left at
  each position (e.g. "RB 6 / 26") — it goes amber, then red, as a
  position gets thin, which is the actual point of building this instead
  of just reading FantasyPros' page directly.
- Rows are grouped by FantasyPros' consensus tier (a divider line marks
  each new tier) — a tier break is usually a real talent drop-off, not
  noise.
- **Undo last pick** / **Reset draft** are there for mis-clicks or a mock
  run-through before Sunday.
- Picks are saved to that browser's local storage only — they don't sync
  anywhere, so use the same browser/device (or re-mark) if you switch mid-draft.

Want it open on your phone too without emailing the file to yourself? Ask
Claude to publish it as a private Claude Artifact — it's a single
self-contained HTML file, so it works as-is.

### Re-ranking without projected points

The free FantasyPros export doesn't include projected fantasy points, only
rank/tier/ADP — so "Value" on the board is a rank-based cushion (how many
spots before a position hits replacement level), not true dollar-value
VBD. If you export FantasyPros' *projections* tool instead (has an
`FPTS`/points column), `build_board.py` will automatically switch to real
points-above-replacement — `vbd.py` detects whichever is present.

## Phase 2 (later): injury data → lineup decisions

Plan: pull weekly injury designations (Out/Doubtful/Questionable) — ESPN's
own sports API exposes this without auth for public player data — and
cross-reference against your actual ESPN roster (via the unofficial
league API below) to flag start/sit risk before lineups lock. Not built
yet; revisit after the draft.

## Phase 3: waiver-wire + start/sit against your league's actual pool

Setup (one time):

1. `pip install -r requirements.txt` (adds `espn_api`, read-only unofficial
   client for ESPN's fantasy API — never used here for anything but
   reading your own league).
2. Copy `.env.example` to `.env` and fill in `ESPN_LEAGUE_ID`,
   `ESPN_S2`, `ESPN_SWID` (see the comments in that file for exactly
   where to find each one). `.env` is gitignored — these are session
   cookies, not an API key, so treat them like a password: never commit
   them, never paste them anywhere but that file.
3. `cd src && python3 check_espn_connection.py` — should print your
   league name, your actual roster (with injury designations), and the
   top free agents by ESPN's own ranking. Run this before trusting
   anything built on top of it.

`espn_client.py` matches "your team" by name (`my_team`/`team_names` in
`league_config.json`) rather than assuming ESPN's internal team ordering
matches our draft-order numbering — those are two independent things ESPN
doesn't guarantee line up.

Once the connection's confirmed: combine `league.free_agents()` (ESPN's
own view of who's actually available in *this* league — no need to
manually cross-reference FantasyPros' rankings against 10 rosters by
hand) with the same VORP logic from `vbd.py`, computed against your
bench's weak spots instead of the whole league, plus FantasyPros' weekly
(not draft) rankings for a second opinion. Not built yet — next step
after the connection check passes.
