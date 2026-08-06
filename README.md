# Dial Command

A [StreamController](https://github.com/StreamController/StreamController)
plugin that runs a different shell command for each dial gesture — clockwise,
counter-clockwise, and press — while tracking a numeric value that the dial
displays, colors itself by, and can sync back from the outside world.

Works on dials and on plain keys (press only).

## Install

StreamController loads plugins from its flatpak data directory, **not** from a
checkout. Editing files in this repo changes nothing until they are copied
over and the app is restarted — plugins are imported once, at startup.

```bash
./deploy.sh
pkill -f StreamController && flatpak run com.core447.StreamController &
```

`deploy.sh` copies into
`~/.var/app/com.core447.StreamController/data/plugins/com_z19r_DialCommand`
and clears stale bytecode (the flatpak runs a different Python than your
host, so `.pyc` files from a host-side test run are not compatible).

Override the destination with `STREAMCONTROLLER_PLUGIN_DIR` if your install
lives elsewhere.

> **Forgetting the restart is the single most common way to conclude "it
> doesn't work".** The old code stays resident until the process dies.

## Settings

| Setting | Meaning |
|---|---|
| ↻ Clockwise Command | Shell command run on a clockwise turn |
| ↺ Counter-Clockwise Command | Shell command run on a counter-clockwise turn |
| ⏎ Press Command | Shell command run on press (or key down) |
| Value File | Optional path the dial reads its value from — see below |
| Minimum / Maximum Value | The range the value is held within |
| Step Size | How much one detent moves the value |
| Base Background Color | Color when no threshold matches |
| Blend Colors | Fade between threshold colors instead of swapping |
| Thresholds | Value breakpoints, each with a color and optional icon |

Commands run through `sh -c` from your home directory. Under flatpak they are
automatically prefixed with `flatpak-spawn --host`, so they run on the host,
not inside the sandbox.

### `{value}` substitution

`{value}` in any command is replaced with the current value before the
command runs. Whole numbers render without a decimal point (`51`, not
`51.0`).

```
pactl set-sink-volume @DEFAULT_SINK@ {value}%
```

### The label

The current value is drawn on the **bottom** label. StreamController only
lets one action own a given label, so if the value doesn't appear, check that
this action holds the bottom label in the input's label settings — the plugin
silently does nothing when it doesn't.

## Reading a value back

The dial keeps its own counter, but a counter drifts: something else changes
the volume, and the dial no longer reflects reality. There are two ways to
tell it the truth.

### 1. Print a number

Anything a command prints on stdout is parsed for its first number.

```bash
#!/usr/bin/env bash
pactl set-sink-volume @DEFAULT_SINK@ +5%
pactl get-sink-volume @DEFAULT_SINK@ | grep -o '[0-9]*%' | head -1
```

Parsing is deliberately loose — `45`, `45%`, `0.45`, `Volume: 45`, and
`45 dB` all yield `45`. The **first** number anywhere in the output wins, so
`12\n34\n` yields `12`; print only what you mean.

**A command gets 0.5 seconds to print.** Anything slower is left running
(never killed, so "launch a long-lived thing" commands stay safe) but its
output is not read. Use a value file for those.

### 2. Write a value file

Set **Value File** to a path and have your script write the current value
there. The dial polls it about once a second and adopts what it finds — no
matter who wrote it.

```bash
#!/usr/bin/env bash
# Clockwise command
pactl set-sink-volume @DEFAULT_SINK@ +5%
pactl get-sink-volume @DEFAULT_SINK@ \
  | grep -o '[0-9]*%' | head -1 > ~/.cache/dial-volume
```

This is the better channel when:

- the command takes longer than 0.5s
- something **other** than the dial changes the value — a daemon, a hotkey,
  another app — and you want the dial face to follow it
- you want the dial to be correct the moment its page loads

The file is parsed exactly like stdout, so the same loose formats work. It is
**read-only** from the plugin's side: the dial never writes it, so ownership
stays unambiguously with your script.

A missing, unreadable, empty, or number-free file is not an error. It means
"no value", and the dial keeps its own counter.

### When both report

| Situation | What the dial believes |
|---|---|
| Only stdout has a number | stdout |
| Only the file moved during the command | the file |
| Both | whichever happened later |
| File unchanged during the command | ignored — see below |
| Neither | its own stepped counter |

That fourth row matters. Without it, a command that prints nothing and
doesn't touch the file would hand back the file's old value and undo the step
you just made — the dial would move one detent and snap back.

Timestamps are compared at nanosecond resolution, so this is well defined
even for near-simultaneous events. **Keep the value file on local storage**:
on a network mount the server's clock stamps the file, and skew against your
local clock breaks the comparison.

### Out-of-range values are rejected

A reported value outside Minimum..Maximum is **discarded with a warning, not
clamped**, from either channel. A script printing garbage cannot drag the
dial to an end stop; the dial keeps its own bookkeeping instead.

The value is only ever *clamped* when it is the dial's own stepping that
reaches an end, or when you narrow the range under an existing value.

## When it syncs

| Moment | What happens |
|---|---|
| Page loads | Reads the file, so the dial is correct immediately |
| Every ~1s | Stats the file; reads and repaints only if the mtime moved |
| Before each turn | Re-reads, so the step is relative to reality |
| After each command | Applies the precedence table above |

The ~1s poll rides `on_tick`, which StreamController already calls for
actions on the active page. There is no background thread and nothing to
leak; a dial with no Value File set does a single dictionary lookup per tick.

## Development

```bash
rtk pytest -q          # 61 unit tests, no GTK or StreamController needed
./deploy.sh            # copy into the flatpak plugin dir
```

`value_parse.py` and `value_source.py` are free of `gi` and StreamController
imports specifically so they can be tested on their own — `value_parse` is
pure, `value_source` is the only module that touches the filesystem. Keep it
that way; the rest of the action can only be exercised by stubbing the host
application.

Design notes live in `docs/superpowers/specs/`.

## Troubleshooting

**Nothing happens at all.** You almost certainly didn't restart
StreamController after `./deploy.sh`.

**The value doesn't show.** Another action owns the bottom label. Reassign it
in the input's label settings.

**The dial moves one step and jumps back.** Your value file holds a stale
number and is being written too late to count. Check the write actually
lands, and check the path.

**A reported value is ignored.** Look for `ignoring ... outside range` in the
log — the number fell outside Minimum..Maximum.

```bash
tail -f ~/.var/app/com.core447.StreamController/data/logs/logs.log \
  | grep -i dialcommand
```
