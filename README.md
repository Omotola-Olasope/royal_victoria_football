# Sets — walk-up football set formation

Built for the Royal Victoria Saturday football group, London. Players record their
own arrival, the app draws the sets, and the whole record is public and
recomputable so no coordinator has to defend a decision.

**Status: live and proven.** Used successfully on a real Saturday with names
entered through the coordinator page.

Backend `Code.gs` version 1.5.1.

---

## What is new in 1.5.1

- **The QR code actually draws.** The encoder is now written into `display.html`
  itself rather than pulled from a CDN, so no browser shield or filter list can
  quietly stop the pitch display working. It is checked module for module against
  a reference encoder across 54 codes, versions 1 to 10.
- **Coordinator page is tabbed**: Pitch, People, Draw, Admin, each with a count,
  so twenty five names no longer means scrolling past everything to reach
  anything. Roster has a search box, long lists scroll inside their card, and on a
  laptop the pitch and queue sit side by side.

## What was new in 1.5.0

1. **You sign in with a player ID, not a name.** Identity is issued by the
   coordinator and can never be minted by a player, so nobody can create a second
   self, hold two arrival slots and keep whichever set he prefers.
2. **Bind once.** The first phone to present an ID owns it. `Release phone` on the
   coordinator page unties it for a new handset.
3. **First bind must happen at the pitch**, which is why IDs can safely be sent
   out in advance. `Allow bind` is the coordinator's ten minute override.
4. **`verification_mode: all`.** GPS first, then the QR on the pitch display.
5. **The QR display works from GitHub Pages** and shows the arrival count. Its
   token endpoint is no longer world readable.
6. **Flagging.** A man who passes by scanning while his phone reports him outside
   the geofence gets in, and gets flagged for the coordinator.
7. Coordinator page shows every ID, and can rename, release and clear flags.

## What was new in 1.4.0

1. **Three selectable draw rules.** `spread` is the new default, `banded` is the
   old one kept frozen, `open` is available one config key away.
2. **Coordinator re-draw**, with a generated nonce so it cannot repeat itself,
   and a latecomer window so admitting a man who turned up ten minutes late is
   your decision rather than the app's.
3. **`Formations` now records everything a draw needs to be reproduced**: rule,
   nonce, latecomer window, set size, max sets and sets on pitch. Previously a
   five a side week could not be verified a month later.
4. **A sandbox test mode** that rehearses on its own day key and cannot touch a
   real Saturday.
5. Coordinator page gained take off, remove and clear day, which the backend has
   always supported and the page never exposed.

---

## Files

| File | Where it lives |
| --- | --- |
| `Code.gs` | Apps Script project bound to a Google Sheet |
| `index.html` | GitHub Pages, the player page |
| `coordinator.html` | GitHub Pages, coordinator only, not shared in the group |
| `display.html` | Apps Script HTML file named `display`, only needed for QR mode. **Not currently installed.** |
| `verify_sets.py` | Independent audit tool, recomputes any draw |

Live at `https://omotola-olasope.github.io/royal_victoria_football/`

## Why the frontend is hosted separately

Apps Script serves web app HTML inside a cross-origin iframe, where browsers
block `navigator.geolocation`. A static page is a top-level document, so GPS
works. Apps Script is the API and the database only.

Requests are POSTed with `Content-Type: text/plain`, because a JSON content type
triggers a CORS preflight Apps Script does not answer.

## Sheets

`Config`, `Players`, `Checkins`, `Sets`, `Formations`, `Audit`.

`session_date` and every `_iso` column are forced to plain text. This matters:
Sheets silently converts date-shaped strings into date values, which broke
filters once and would corrupt the draw seed if it happened to a timestamp.
`readRows_` also normalises both on read, as a second line of defence, and now
does the same for `verify_ok`, which would otherwise empty the pool silently if
that column ever came back as the string `"TRUE"`.

## Config keys

| Key | Live value | Notes |
| --- | --- | --- |
| `pitch_name` | Royal Victoria Football | |
| `timezone` | Europe/London | |
| `session_days` | SAT | Accepts `ANY`, `SAT`, `SATURDAY`, `SAT,SUN` |
| `cutoff_time` | 10:00 | Accepts `H:MM`, `HH:MM`, `HH:MM:SS` or a Sheets time value. Unreadable values raise an error rather than defaulting |
| `set_size` | 5 or 6 | 5 when keepers stand outside and play every set. Set it before the cutoff; changing it after the draw will not rebuild the sets |
| `max_sets` | 8 | Rotation capacity |
| `sets_on_pitch` | 2 | How many sets play at once |
| `draw_rule` | spread | `spread`, `banded` or `open`. An unrecognised value raises an error |
| `allow_new_sets_after_cutoff` | TRUE | |
| `verification_mode` | all | `all`, `none`, `gps`, `qr`, `nfc`. `all` is GPS then QR. An unrecognised value raises an error |
| `geofence_lat` / `geofence_lng` | 51.4998 / 0.06674 | The pitch |
| `geofence_radius_m` | 150 | |
| `max_accuracy_m` | 50 | **Must be well inside the radius.** The check compares the reported point against the radius and does not widen it by the accuracy, so a tolerance larger than the radius makes the geofence meaningless |
| `one_player_per_device` | TRUE | |

Config is cached for 60 seconds. `setup()` is safe to re-run: it adds config keys
introduced by a later version without touching existing values, and now also adds
sheet columns introduced by a later version.

---

## The draw

Arrival order decides **whether you play** and, under two of the three rules,
**how soon**. The rule decides only **who you stand beside**.

At the cutoff, over everyone who checked in before it:

1. Sort by server timestamp, player id breaking ties.
2. `playable = min(floor(present / set_size) * set_size, set_size * max_sets)`.
   The earliest `playable` arrivals get places; the rest queue in arrival order.
3. Seed a SHA-256 from the canonical string `player_id@timestamp|...` of exactly
   those chosen players. For a re-draw, a nonce is stirred into the resulting
   hash afterwards, never into the canonical string, so every draw recorded
   before 1.4.0 still reproduces byte for byte.
4. Hand the chosen players to the selected rule.

The cutoff is a filter on the data, not a scheduled event, because Apps Script
triggers fire within a window rather than at a precise second. The first request
after the cutoff computes the draw; `ensureFormation_` re-checks inside the lock
so two simultaneous requests cannot both form it.

After the cutoff, check-ins join a strict FIFO queue. Vacancies go to the front
of the queue. When the queue reaches a full set and the pitch has room, a new set
forms through the same seeded draw.

All writes go through `LockService`.

### The three rules

**`banded`** — the original, frozen. Arrivals are cut into bands of
`set_size * sets_on_pitch`, the group that goes on the pitch together. The first
twelve fill the two sets that start, the next twelve the two that follow. Each
band is shuffled whole.

**`spread`** — the default. Bands are exactly as `banded` leaves them, so arrival
fairness is identical. What changes is inside a band: instead of shuffling twelve
people and cutting them in half, the band is cut into strata of `sets_on_pitch`,
each stratum shuffled and dealt one player per set. Men who tap in one after
another usually land in the same stratum, and the same stratum makes sharing a
set impossible.

A tail too short to fill `sets_on_pitch` sets is absorbed into the band before
it, so it is not left as a lone unmixed set. **Never when that would leave fewer
than three bands**, because with two bands the merge widens the opening band and
an early arrival can be dealt into a set that goes on second. That is the one
thing this rule exists to prevent, and it was a real defect caught by the tests.

**`open`** — what the group originally asked for. The first `sets_on_pitch`
arrivals are guaranteed a place in the sets that start; everyone else is
randomised across every set regardless of arrival time.

### Measured behaviour

Four thousand seeded draws per cell, run against the shipping `verify_sets.py`.
"Adjacent pair" means two men who tap in back to back, which is what arriving
together looks like in the log.

42 players, six a side, two sets on the pitch:

| rule | adjacent pair | adjacent trio | worst displacement | early arrivals bumped |
| --- | --- | --- | --- | --- |
| `banded` | 48.7% | 23.5% | 0 rotations | 0 of 12 |
| `spread` | 16.1% | 0.0% | 1 rotation | 0 of 12 |
| `open` | 12.0% | 1.1% | 3 rotations | 7.5 of 12 |

25 players, five a side, where `spread` beats `open` on both counts:

| rule | adjacent pair | adjacent trio | worst displacement | early arrivals bumped |
| --- | --- | --- | --- | --- |
| `banded` | 50.0% | 24.7% | 0 | 0 of 10 |
| `spread` | 13.9% | 0.0% | 1 | 0 of 10 |
| `open` | 15.9% | 2.1% | 2 | 5.2 of 10 |

Swept over every turnout from 6 to 72, four to seven a side, one to four sets on
the pitch: `banded` never displaces anyone, `spread` never exceeds one rotation
and never bumps a man out of the opening rotation, and `open` reaches seven
rotations of displacement at one set on the pitch.

### The honest limitation

When turnout leaves a band that produces only one set, those men arrived
consecutively and will play together whatever rule is selected. At 17 players
five a side, arrivals 11 to 15 are a set with nothing to mix against. This cannot
be fixed without widening the opening band, which would bump early arrivals. The
coordinator page says so on screen when it happens.

---

## Re-drawing

A button on the coordinator page clears every set for the day and draws again
from whoever is still here.

- The old `Sets` rows are marked `redrawn`, never deleted. Both draws stay in the
  sheet and both stay verifiable.
- The `Formations` row for the original cutoff draw stays in place, so
  `ensureFormation_` does not form a third draw on the next poll.
- Anyone who left or was taken off stays out.
- A **nonce** is generated by the backend, recorded in `Formations`, and shown on
  both pages. Without it, re-drawing the same pool would reproduce the identical
  sets, because the seed comes from the arrival log alone. It is generated rather
  than typed: a nonce the coordinator could choose is a nonce he could keep
  retyping until he liked the sets, and only the one he kept would be recorded.
- Nothing stops him pressing the button five times. The record is the check:
  every re-draw writes its own row with its own nonce and timestamp, and the
  player page shows the count, so five presses look like five presses.

### The latecomer window

Measured **from the cutoff**, never from the moment the button was pressed. A ten
minute window means everybody who arrived before 10:10, whether you re-draw at
10:12 or at 11:05. Measured from the press it would depend on when you happened
to tap and nobody could reproduce it.

Offered on the page: cutoff only, 5, 10, 15, 30, 45 minutes, or everyone. A man
outside the window is not shut out of the morning; he stays in the queue and
still takes a vacancy if somebody drops out.

---

## Auditing

Every formation writes its rule, nonce, window, sizes, seed and canonical input
to `Formations`. Export the arrival log and run:

```bash
# a cutoff draw
python verify_sets.py arrivals.csv --rule spread --set-size 5 \
    --max-sets 8 --sets-on-pitch 2 --expect-seed <seed>

# a re-draw, with the nonce and window from the same Formations row
python verify_sets.py arrivals.csv --rule spread --set-size 5 \
    --nonce <nonce> --cutoff 2026-08-15T09:00:00.000Z --late-window 10 \
    --expect-seed <seed>
```

Every argument is written in the `Formations` row for that draw. You should never
have to remember what the settings were.

The Python port of mulberry32 is bit-for-bit identical to the Apps Script
generator. All three rules were cross-checked by loading the real `Code.gs` into
Node and comparing set membership against `verify_sets.py` over 504 cases:
turnouts 11 to 55, five and six a side, one to three sets on the pitch, with and
without a nonce. Zero mismatches. `banded` was separately checked against the
1.3.0 implementation in both languages, so every draw already recorded still
reproduces.

---

## Testing without destroying a real Saturday

**Do not run `simulate()` on a day that holds real arrivals.** It deletes every
row carrying that date. It now refuses to run and tells you to use `testStart()`.

**Do not run `goLive()` to test.** It empties every sheet across every date.

Use the sandbox:

```
testStart(25)     twenty five men, six of them late, on a sandbox day
testStart(40)
testStart(17)
testStatus()      is a sandbox running, and when does it expire
testEnd()         delete the rehearsal, bring the real day back
```

The whole app moves onto a key like `SIM-20260815-141203`, which is deliberately
not date shaped so Sheets cannot coerce it. Real rows sit underneath untouched.
Both pages work exactly as they do on a Saturday and show a red test mode banner.
Latecomers are seeded at 3, 8, 12, 20, 35 and 50 minutes past a synthetic cutoff
so the window controls have something real to bite on, and two men are taken out
in advance, one as though he went home and one as though you pulled him, so the
vacancy and takeoff paths are exercised too.

A sandbox expires by itself after three hours, so a forgotten one cannot still be
running next Saturday.

## Editor functions

| Function | Purpose |
| --- | --- |
| `setup()` | Builds sheets, seeds config, adds missing keys **and missing columns**, sets text formats. Safe to re-run |
| `selfTest()` | Confirms the seed is deterministic and the shuffle reproducible |
| `diagnose()` | Prints today's key, session day, raw and parsed cutoff, and what each check-in row holds |
| `testStart(n)` | Rehearsal on a sandbox day. Destroys nothing |
| `testStatus()` | Whether a sandbox is running |
| `testEnd()` | Ends the rehearsal, restores the real day |
| `simulate(n)` | Old rehearsal, in-place. Refuses if real arrivals exist for the day |
| `wipeTestData()` | Removes simulated players and today's rows |
| `goLive()` | **Destructive.** Clears all history from every date |
| `removePlayer(name)` | Removes one registration |
| `showCoordinatorKey()` | Prints the admin key |

## Signing in

A man opens the app, types the ID the coordinator gave him, and the phone is
bound to him for good. He never types it again.

- IDs are hex, so `O` is read as zero and `I` or `L` as one. Case, spaces and
  dashes are ignored. Nobody fails because he misheard a letter across a pitch.
- The first phone wins. A second is refused and sent to the coordinator.
- The first bind must pass verification, so it happens at the pitch. **That is why
  IDs can be sent out the night before.** Send them privately, one to one, not as
  a list in the group.
- `Allow bind` opens ten minutes for one man, recorded in `Audit` as
  `coordinator_grant` so it is visibly different from one earned at the pitch.

## The pitch display

`display.html` needs `API_URL` set, and the coordinator page unlocked once on the
same device: both pages share an origin, so it reads the key from local storage
and nothing secret goes into the repository.

It shows the rotating code, the arrival count, and how many check-ins are waiting
to be looked at. It holds a screen wake lock so a propped-up phone does not sleep.

## Coordinator page

Gated by the admin key, stored in Script Properties. Operations: `roster`,
`checkin_for`, `mark_off`, `remove_checkin`, `reset_session`, `redraw`,
`set_rule`.

`checkin_for` creates the player if unknown, so a man with no phone, not in the
WhatsApp group, or who just walked over can be recorded. It stamps the moment the
coordinator taps, records `verify_method` as `coordinator`, and writes to `Audit`,
so assisted arrivals are visibly distinct from self-recorded ones.

Clear day is gated behind typing `CLEAR` and then a confirm, because it is one
tap away from the buttons you use every week.

Two coordinators can record simultaneously; the script lock serialises writes and
duplicate names are rejected with the existing arrival time.

---

## Deploying a change

**Backend.** Paste `Code.gs`, save, then **Deploy, Manage deployments, pencil
icon, Version set to New version, Deploy.**

Choosing "New deployment" instead issues a *different* URL and the frontend keeps
calling the old one, so the app carries on serving stale code and nothing appears
to have changed. This is the single easiest mistake to make here.

After deploying 1.4.0, **run `setup()` once from the editor.** It adds the
`draw_rule` config key and the six new `Formations` columns. Nothing works
correctly until it has run.

**Frontend.** Commit to GitHub, wait about a minute for Pages, hard refresh.

---

## Bugs already found and fixed, do not reintroduce

1. Sheets converting `session_date` to a date value, so every filter silently
   matched nothing.
2. `cutoff_time` of `07:30:00` failing a strict `HH:MM` regex and silently
   defaulting to 10:00.
3. `Utilities.formatDate(..., 'EEE')` for the day of week, which is locale
   dependent and would never match `SAT` in a non-English project.
4. The 8 second poll rebuilding the DOM unconditionally, destroying whatever was
   being typed into the name field.
5. A background poll accepting a non-state reply and then crashing on
   `s.is_session_day`, showing a raw JavaScript error to players on an idle page.
   Background polls now fail silently and replies are shape-checked.
6. `readRows_(Players)` called inside a filter callback, once per check-in row.
7. `setup()` could not add a column to an existing sheet, because header creation
   was gated on an empty sheet. `appendRows_` would then have written new values
   into unheadered columns that `readRows_` can never see. It now migrates, and
   hard-stops if anyone has reordered a header by hand.
8. `verify_ok` compared with `=== true`, so the same cell arriving as the string
   `"TRUE"` after a hand edit or CSV round trip would have emptied the pool
   silently, exactly like bug 1.
9. `mark_off` marked the `Sets` row but not the `Checkins` row, so a man you took
   off dropped back into the queue as the earliest waiting arrival and
   `fillVacancies_` put him straight back into the slot you had just removed him
   from.
11. `doGet` served `qr_token` with no authentication, so anyone holding the web
    app URL could fetch the live QR code from anywhere and check in as though
    standing on the pitch. Now an authenticated admin operation.
12. `checkIn_` only requested a location when the mode was exactly `gps`, so
    under `all` no location was ever sent and GPS could never pass.
13. `display.html` called `google.script.run`, which does not exist on GitHub
    Pages, so the page threw once a second for ever and showed only "loading".
14. The boolean config parser treated anything that was not the literal word
    FALSE as TRUE, so a typo or a key name pasted into the value column read as
    TRUE silently.
16. `display.html` drew its QR from a CDN script. On a browser that blocks it,
    the draw threw, and because `lastToken` was set before the draw rather than
    after, every later poll skipped drawing while the count, title and progress
    bar all kept updating, so the page looked healthy with an empty white square.
    The encoder is now inlined and `lastToken` is set only on success.
17. The inlined encoder itself had three faults caught by checking it against a
    reference: byte-mode character capacity used where data codeword capacity was
    needed, format bits reversed in one copy and swapped in the other, and no
    version information block for versions 7 and up.
18. The `spread` tail merge could collapse to a single band and widen the opening
    band, bumping early arrivals into later sets. Caught by the property tests
    before it shipped.
