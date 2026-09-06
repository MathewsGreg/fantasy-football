# Fantasy Football

Tools for a 10-team half-PPR ESPN league: a draft-day board (VORP/VONA
against our actual roster construction) and, once the season's under way,
a weekly report of start/sit suggestions and waiver-wire targets ranked
by FantasyPros' weekly rankings, cross-referenced against live ESPN
league data. Split out of the `mlb-elo` repo into its own
project once the draft-board work was done — no functional connection to
that project, just born from the same sessions (a couple of comments
still point back to its `daily_refresh.ps1` as the pattern this one's
scheduled-task script follows).

## Status

**Draft board (phase 1): done**, used for the actual 2026 draft. No known issues.

**Weekly report (phase 3): sourcing flipped, not yet re-verified against a
real live run.** FantasyPros' weekly rankings are now the authoritative
source for lineup order and waiver targets — ESPN's `percent_owned`/
next-game projection moved from "the ranking signal" to "commentary shown
alongside FantasyPros' rank." Everything below this paragraph up through
"FantasyPros' weekly rankings appear to exclude players ruled out..." was
verified under the *old* ESPN-authoritative design; the underlying ESPN
API quirks it documents (D/ST status string, free-agent position label,
missing ownership on `box_scores()`, `ir_eligible` semantics) still apply
unchanged, since they're about reading ESPN data, not about how that data
gets ranked. What specifically has NOT been re-run against a real league
since the flip: does `fp_blend.py`'s name-matching actually find enough
of your real roster/free-agent pool in a live FantasyPros export to
produce a useful lineup and Waiver Targets list, or does coverage turn
out thinner in practice than expected. The flip itself was only
exercised with fabricated names/ranks in a throwaway script (no real
ESPN or FantasyPros data touched it) — worth a manual
`python weekly_report.py` run against real ESPN + a fresh FantasyPros
export before trusting it for an actual waiver decision.

**Previously verified, under the old ESPN-authoritative design, against
the real league across several rounds of actual data** (not just
synthetic tests) — the ESPN connection, lineup diff, waiver ranking, IR
handling, and the FantasyPros weekly blend have all been run against
real roster/rankings data and fixed where reality disagreed with the
first assumption:

- ESPN reports a healthy D/ST's `injuryStatus` as `'NORMAL'`, not
  `'ACTIVE'` or blank — handled in `HEALTHY_STATUSES`
  (`weekly_report.py`).
- `league.free_agents(position=...)` needs ESPN's raw label `'D/ST'`
  (with the slash), not our normalized `'DST'`, or the position filter
  silently no-ops and returns whatever's highest-owned overall instead
  — see `ESPN_FREE_AGENT_POSITION`.
- `box_scores()` (what the lineup/roster comes from) doesn't carry
  ownership data at all — `percent_owned` comes back `-1` for your own
  roster from that call. `backfill_percent_owned()` does a separate
  `player_info()` call to get real values before ranking any moves.
- A player's `ir_eligible` flag can be `True` even when completely
  healthy, if your league's IR-slot setting allows any rostered player
  (not just injured ones) — confirmed on a real healthy player.
  `move_rationale()` says this plainly rather than implying an injury
  that isn't there.
- FantasyPros' weekly rankings appear to exclude players ruled out for
  the week entirely (a real OUT player was simply absent from the RB
  file) — expected, not a bug; those players just get no FantasyPros
  annotation that week.

**Not yet confirmed: the Windows Task Scheduler automation actually
firing unattended.** `scripts/weekly_refresh.ps1` is written and set up
per the instructions below, but every run so far has been a manual
`python weekly_report.py` — the 3x/week scheduled trigger hasn't been
observed firing on its own yet. Worth checking the first Tuesday/
Thursday/Sunday after setup: confirm a log appears in
`%LOCALAPPDATA%\fantasy_football\logs\` and `docs/index.html` updates
without you touching the machine.

**Open questions, flagged but not acted on:**
- `positional_need()` counts roster depth without discounting injured
  players, so a position can read "full" even when its *healthy* depth
  is thin. Revisit if the need tags feel unhelpful in practice.
- `MIN_RANK_IMPROVEMENT` (5 FantasyPros rank spots, replacing the old
  ownership-based `MIN_OWNERSHIP_GAP`) is an unvalidated judgment call —
  the old ownership threshold had at least one real Top Waiver Move land
  right at it (defensible, not compelling); this new rank-based one
  hasn't been checked against a real week's numbers at all yet. Revisit
  once it has.
- Automating the FantasyPros CSV pull itself (their sanctioned path is
  a paid personal API key, ~$8.99/mo) was considered and declined in
  favor of the free manual export. Revisit if that calculus changes.

**For a fresh Claude session picking this up later:** this README plus
the git log (`git log --oneline`) is the full history and reasoning —
no other context is needed. Point a new session at
`mathewsgreg/fantasy-football` and it can start from here.

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

**FantasyPros' weekly rankings are the authoritative source for lineup
order and waiver targets.** ESPN's live league data — your current-week
box score (real slot assignments, injury/bye status, matchup), and each
player's `percent_owned`/next-game projection — supplies everything
FantasyPros' export doesn't (who's actually on your roster, who's
actually a free agent right now) and is shown alongside every pick as
commentary, never as what decides the pick. This flipped from an earlier
version where ESPN's own projection/ownership drove everything and
FantasyPros was only a second opinion — see the git log around the
commit that made this change if you want the full before/after.

`weekly_report.py` pulls your current-week box score (real ESPN slot
assignments, not a hand-reconstructed roster) and `lineup.py` suggests a
lineup ordered by each player's FantasyPros weekly position rank
(`attach_fp_ranks()` looks it up per roster player), diffing it against
what ESPN actually has you starting. A player FantasyPros doesn't rank
this week (no CSVs loaded, or genuinely absent from that position's
export — e.g. a deep bench stash) sorts after every ranked player;
ESPN's own projection is used only to order that unranked group among
itself, never to outrank someone FantasyPros did rank. Waiver targets
are `league.free_agents()` filtered down to only players FantasyPros
ranks this week, sorted by that rank, then grouped by whether the
position is short/ok/full against `my_roster_targets`. Writes
`docs/index.html` — **deliberately doesn't publish FantasyPros' rankings
table itself**, only this derived analysis.

The page opens with **Top Waiver Moves**: up to 5 explicit add/drop
pairings (add this free agent, drop this bench player), each with a
one-line rationale, ranked by the FantasyPros rank gap between the two.
For each position, it compares the best FantasyPros-ranked available
free agent against your *worst* FantasyPros-ranked bench player — a
bench player FantasyPros doesn't rank at all this week is skipped as a
drop candidate rather than assumed droppable (don't guess). Deliberately
doesn't require the free agent to be healthy *this week*: a hurt or IR
player FantasyPros still ranks well ahead of your bench guy surfaces as
a stash recommendation even though he can't play this week; the
rationale says so explicitly either way. If nothing clears a small
minimum rank improvement (`MIN_RANK_IMPROVEMENT`, currently 5 rank
spots — enough to filter out noise without being so strict it hides real
opportunities), it says there's nothing worth doing rather than
manufacturing a move.

Waiver Targets by position go 10 deep for RB/WR (scarce, season-swinging
positions worth digging into, injured stashes included) and 5 deep for
QB/TE/K/DST (thin, mostly interchangeable past the top few) —
`DEFAULT_WAIVER_DEPTH` in `weekly_report.py` if you want to change that.
A position can come back shallower than that if FantasyPros simply
doesn't rank that many free agents this week — the list is never padded
out with ESPN-only, FantasyPros-unranked players to hit the depth target.

### FantasyPros weekly rankings

Unlike the draft-day export (one combined "ALL positions" file),
FantasyPros' *weekly* rankings are one page per position with no
combined download, and the "Flex" page (which does combine RB/WR/TE)
mixes them into one cross-position order rather than giving each
player's rank within their own position — not what we want here. So:
download each position separately from FantasyPros' weekly rankings
(as many as you care about — any subset is fine, missing ones just mean
no lineup/waiver ranking for that position that week).

**No renaming needed** — just drop FantasyPros' own downloads (e.g.
`FantasyPros_2026_Week_1_RB_Rankings.csv`) straight into `data/weekly/`
(create the folder if it doesn't exist — gitignored, same reasoning as
the draft board's `cheatsheet.csv`). `fp_blend.py` reads the position
*and* the week number straight out of the filename (there's no POS
column in this export at all, since each file's already one position),
and always uses whichever week is newest per position. That means
`data/weekly/` doubles as a permanent history — every Tuesday, just
drop the new files in without deleting the old ones, and last week's
export quietly stops being used without you having to do anything
about it. A stray Flex file sitting in the same folder is harmless —
its filename doesn't match any of the six real positions, so it's
silently ignored.

`fp_blend.py` matches every player ESPN shows you by name, or by team
abbreviation for DST (ESPN says "Texans D/ST", FantasyPros says
"Houston Texans" — matching on team code sidesteps that). Every starter,
bench player, and Waiver Target row shows FantasyPros' position rank
(and grade, when ranked) as the primary column, with ESPN's
`percent_owned`/next-game projection alongside it as commentary — shown
side by side, deliberately **not fused into one score**, since different
scales would hide real disagreement between the two instead of
surfacing it.

**FantasyPros stays authoritative even when its data is stale — the
report never silently falls back to ESPN's numbers.** Since
`weekly_report.py` runs unattended 3x/week but `data/weekly/` only
updates when you manually drop in a new export, the report always
publishes the exact date FantasyPros' currently-used data was last
refreshed (`blend.as_of_str`, from whichever per-position file is
oldest) right at the top of the page, and flags it if it's past
`STALE_AFTER_DAYS` (8) — but keeps using it regardless, on the theory
that slightly-stale FantasyPros rankings are still a better authority
than switching to ESPN's numbers for that run. If `data/weekly/` has no
files at all, there's no FantasyPros data to fall back to being stale
on — lineup order falls back to ESPN's projection for every player (the
old behavior, since nothing is ranked either way) and Waiver Targets
comes back empty for every position, with the page saying so plainly
rather than silently running on absent data.

Automating the CSV pull itself was considered and deliberately skipped:
FantasyPros' free page export is built for a person to click, not a
script to hit unattended, and their sanctioned path for that (a real
public API with a personal tier, ~$8.99/mo) costs money for something
that already works as a 30-second manual step. Revisit if that
calculus changes.

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
