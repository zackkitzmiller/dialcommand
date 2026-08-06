# Value file sync — design

**Date:** 2026-08-06
**Status:** approved

## Problem

A dial's value can change without the dial being turned. Something else
adjusts the volume; a script finishes long after the dial fired. Today
DialCommand has one inbound channel — the command's stdout, read for at most
`COMMAND_TIMEOUT` (0.5s). Two things are therefore impossible:

1. A command slower than 0.5s can never report its result.
2. A process that never went through the dial cannot tell the dial anything.

The dial's internal counter drifts from reality, and the next turn steps from
that stale number.

## Solution

An optional file the dial reads. The called script — or anything else on the
system — writes the current value there, and the dial syncs from it.

## Settings

One new row: **Value File** (path, `EntryRow`, `var_name="value_file"`).

Empty is the default and disables everything below. Behavior with it empty is
byte-for-byte today's behavior.

## Format and validation

The file's contents go through the existing `parse_number`, so `45`, `45%`,
`0.45`, and `Volume: 45` all work — identical to how stdout is parsed.

Values outside the configured `min`..`max` are **rejected, not clamped**,
reusing `in_range`, and logged as a warning. This matches the rule already
applied to stdout: a source reporting nonsense cannot drag the dial to an end
stop.

A missing, unreadable, or non-numeric file is not an error. It means "no
value" and the dial keeps its own counter. The condition is logged once on
transition, never on every tick, so a mistyped path cannot spam the log at
1 Hz.

## Reading: on_tick, not FileMonitor

StreamController already calls `action.on_tick()` about once a second
(`DeckController.py:1794`, `TICK_DELAY = 1`), only for actions on the active
page. The tick `stat()`s the file and reads it only when `st_mtime_ns` has
moved.

`Gio.FileMonitor` was considered and rejected:

| | on_tick + mtime | Gio.FileMonitor |
|---|---|---|
| Latency | ≤1s | ~instant |
| Teardown | nothing to leak | must cancel in `on_removed_from_cache()`, a `#TODO: Fully implement` stub |
| Precedent | heartbeat already exists | no plugin on this system uses one |

≤1s is indistinguishable from instant for a value a human reads off a dial
face, and the tick carries no lifecycle risk. Revisit only if sub-second
response proves necessary.

## Flow

**On tick** — `stat()`; if mtime unchanged, stop. Otherwise read, parse,
range-check, apply, repaint.

**On turn** — read the file *first*, so the step is relative to reality rather
than to a possibly stale counter. Then step, then run the command.

**After a command returns** — capture `time.time_ns()`, `stat()` the file, and
take whichever is later:

```
T_file > T_cmd  ->  file value wins
otherwise       ->  stdout value wins
neither usable  ->  keep internal counter
```

### Why "newer" is well defined

Measured on this machine: `st_mtime_ns` and `time.time_ns()` are
nanosecond-resolution and share a clock domain, agreeing to within ~10µs; five
writes 3ms apart produced five distinct mtimes. Sub-second ordering is real,
not a coin flip.

When a single script both prints a number and writes the file, the two carry
the same value and the ordering is moot. "Newer" only does work when
something *else* touched the file mid-command — the case this feature exists
for.

Known limitation: a value file on a network mount is stamped by the server's
clock, not the local one. Skew there breaks the comparison. Local paths only.

## Direction

Read-only. The dial never writes the value file; `{value}` substitution stays
the only outbound channel. This keeps ownership of the file unambiguous and
avoids the dial and the script racing to write the same path.

## Structure

New module `actions/DialCommand/value_source.py`. `value_parse.py` documents
itself as free of gi/StreamController imports and purely functional;
filesystem IO does not belong there.

- `read_value_file(path) -> (value, mtime_ns)` — filesystem, tested with
  `tmp_path`
- `pick_newer(stdout_val, cmd_ns, file_val, file_ns) -> float | None` — pure,
  and the primary test target, since precedence is where bugs will live

## Testing

Tests first. `pick_newer` gets the bulk of the coverage: file newer, stdout
newer, equal timestamps, either side missing, both missing. `read_value_file`
covers a good file, absent file, empty file, garbage contents, and a
permission error.
