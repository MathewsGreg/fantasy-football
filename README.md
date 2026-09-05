# Fantasy Football

Tools for a 10-team half-PPR ESPN league: a draft-day board (VORP/VONA
against our actual roster construction) and, once the season's under way,
a weekly report of start/sit suggestions and waiver-wire targets pulled
from live ESPN league data. Split out of the `mlb-elo` repo into its own
project once the draft-board work was done — no functional connection to
that project, just born from the same sessions (a couple of comments
still point back to its `daily_refresh.ps1` as the pattern this one's
scheduled-task script follows).

## Draft board

A companion tool that turns a FantasyPros consensus-rankings export into
a live draft-day board: sortable/filterable player list, consensus tiers,
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
4. Save it as `data/cheatsheet.csv` (gitignored — it's FantasyPros'
   content, not something to publish).

### 2. Build the board

```
cd src
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

## Phase 2: injury data → lineup decisions

Folded into phase 3 rather than built separately: `weekly_report.py`
pulls each roster player's ESPN injury designation (and bye-week status)
straight from the same box-score call used for projections, and
`lineup.py` hard-excludes Out/IR/suspended/bye players from the suggested
lineup while soft-flagging Questionable/Doubtful ones. See phase 3 below.

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

### The report

`weekly_report.py` pulls your current-week box score (real ESPN slot
assignments + per-week projections, not a hand-reconstructed roster),
suggests a lineup by projection (`lineup.py`), diffs it against what
ESPN actually has you starting, and ranks `league.free_agents()` by
position — grouped by whether that position is short/ok/full against
`my_roster_targets`, not one fake cross-position score. Writes
`docs/index.html` — **deliberately doesn't publish FantasyPros' rankings
table itself**, only this derived analysis from your own live league data.

Run it directly: `cd src && python3 weekly_report.py`.

### Publishing it (GitHub Pages, one-time)

This repo's `docs/index.html` needs GitHub Pages turned on before it's
reachable anywhere: on GitHub, **Settings → Pages → Build and
deployment → Source: "Deploy from a branch" → Branch: `main` /
`docs`**. Save, then it's live at `https://mathewsgreg.github.io/fantasy-football/`
a minute or two later (and stays at that URL — later pushes to
`docs/index.html` just update it).

### Automating it (Windows Task Scheduler)

`scripts/weekly_refresh.ps1`: run the report, commit + push
`docs/index.html` only if it changed, log everything, abort loudly (not
silently) on any failure.

One-time setup:

1. Clone this repo locally, e.g. to
   `C:\Users\Diggs\Dropbox\PC\Documents\Claude\fantasy_football` (matches
   the path `weekly_refresh.ps1` expects — edit `$Repo` at the top of
   that script if you put it somewhere else).
2. Create a dedicated venv (kept outside the Dropbox-synced folder to
   avoid file-locking mid-install, same reasoning as the sibling MLB
   project's):
   ```
   "C:\Users\Diggs\AppData\Local\Programs\Python\Python312\python.exe" -m venv "C:\Users\Diggs\venvs\fantasy_football"
   "C:\Users\Diggs\venvs\fantasy_football\Scripts\python.exe" -m pip install -r requirements.txt
   ```
3. Confirm `.env` (repo root) has real values (see Setup above) — the
   scheduled task runs unattended, so this has to already be in place.
4. Open **Task Scheduler** → Create Task (not "Basic Task", so you can
   add multiple triggers on one task):
   - **General**: name it e.g. "Fantasy Weekly Refresh"; "Run whether
     user is logged on or not" if you want it to fire even when you're
     away from the machine.
   - **Triggers** → New, three times:
     - Weekly, Tuesday, 9:00 AM (waiver planning — after the week's
       games are final, before Tue-night/Wed-morning waiver processing)
     - Weekly, Thursday, 9:00 AM (start/sit ahead of the Thursday night
       game)
     - Weekly, Sunday, 11:00 AM (start/sit ahead of the early/late
       Sunday windows, once most injury news is in)
   - **Actions** → New → Program/script: `powershell.exe`; Arguments:
     `-ExecutionPolicy Bypass -File "C:\Users\Diggs\Dropbox\PC\Documents\Claude\fantasy_football\scripts\weekly_refresh.ps1"`
   - **Conditions**: uncheck "Start the task only if the computer is on
     AC power" if this runs on a laptop, or it'll silently skip on
     battery.
5. Right-click the task → Run, once, to confirm it works before trusting
   the schedule — check the log in `%LOCALAPPDATA%\fantasy_football\logs\`
   and that `docs/index.html` actually updated (and, once Pages is on,
   that the live URL reflects it).

This only ever pushes if the branch is `main` — if you're testing from a
feature branch, `git checkout main` first (after merging) or the script
aborts rather than committing somewhere the schedule won't find next time.
