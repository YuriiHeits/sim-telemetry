# Pit-stop-aware session logging

Status: approved design, not yet implemented.

## Problem

`stint_logger.pyw` currently closes the current CSV the instant the car
enters the pit (`in_pit and not self.prev_pit`), and separately closes
after 3s parked when not in pit. That means:

- One session (practice, quali, or a race with pit stops) is scattered
  across many small files, one per stint — annoying to review and
  breaks any attempt at whole-session stint analysis.
- Pit-stop telemetry (fuel added, tyre swap, repair time) is never
  written at all, since recording stops the moment `in_pit` goes true.
- A real pit stop that legitimately takes longer than a short timeout
  (heavy suspension/bodywork repair, 90s+) would get cut off mid-stop
  if we naively replaced "close on pit entry" with a flat AFK timer.

## Design

### 1. File boundary = session type, not pit stop

`session_key` (currently `(car, track, day)`) gains the session tag
(`sess_name(g.session)`), so it becomes
`(car, track, day, tag)`. A tag change (PRACTICE → QUALI → RACE)
resets lap history / fuel plan exactly like a car/track change does
today, and forces a file close + reopen. Result: at most 3 files per
event (practice / quali / race), each spanning every pit stop within
that session.

### 2. Two independent AFK timeouts, both configurable (`logger.cfg`)

- **`afk_timeout_s`** (default 30) — applies when the car is stopped
  and **not** in pit. Covers: parked in the garage, stopped mid-track
  in AC drift practice (no pit box on the map, `isInPit` never true —
  same rule applies, no special-casing needed), or a crashed/blocked
  car after a teleport (speed sits at 0, this timer eventually closes
  it — no separate crash detection needed).
- **`afk_pit_timeout_s`** (default 600–900, i.e. 10–15 min) — applies
  only while `in_pit` is true. Protects a real, slow pit stop (fuel +
  tyres + heavy repair) from ever being cut off mid-service, while
  still closing the file if the car is genuinely abandoned in the pit
  box for a long time.

Both get the same `load_*`/`save_*` pattern as `load_plan_minutes()`,
and a small Entry field in the UI next to the existing PLAN field.

### 3. Session-type-dependent pit behavior

- **RACE**: pit stops never force a new file — hardcoded, no toggle.
  Continuity across every mandatory/strategy stop matters more here
  than in practice.
- **PRACTICE / QUALI**: new toggle, `close_on_pit_practice` (default
  `false`). When `true`, restores today's behavior (new file per pit
  visit) for anyone who prefers reviewing each run separately.

### 4. Poll loop changes

- Remove `if in_pit and not self.prev_pit: self._close()`.
- Remove the immediate `elif in_pit: self._close()`.
- Unify the moving/stopped tracking so it runs regardless of `in_pit`,
  writing rows the whole time (pit-stop telemetry — fuel add, tyre
  compound/pressure change — becomes visible in the CSV for the first
  time).
- Stopped-timer picks `afk_pit_timeout_s` or `afk_timeout_s` depending
  on current `in_pit`, and — for PRACTICE/QUALI with
  `close_on_pit_practice=true` — the old instant-close-on-pit-entry
  path still fires instead of the timer.

### Side benefit

`race_report.py` already splits a file into stints by the `inpit`
column — that logic has never actually been exercised because stints
were always in separate files. Once one file can contain multiple pit
stops, its stint table finally shows what it was built to show.

## Explicitly out of scope

- Detecting "car damaged/blocked" via `carDamage` or similar — the
  existing speed-based AFK timer already handles it as a side effect.
- Row-throttling while genuinely idle in the pits for hours — real
  cost is ~33 MB/hour at the observed ~32 rows/s, acceptable for the
  rare edge case; not worth the complexity.

## Testing

No live sim available at design time (post-race). Verify manually next
session: confirm 3 files appear across a practice→quali→race sequence,
confirm a pit stop mid-race does not split the file, confirm both AFK
timeouts fire at their configured durations.
