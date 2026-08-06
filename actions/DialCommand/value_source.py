"""Reading dial values written by something other than the dial itself.

The dial's command is not the only thing that can change the value it
represents -- another app adjusts the volume, a script finishes long after
the dial fired. A value file gives those a way to report back.

Filesystem access lives here rather than in value_parse, which is
deliberately pure.
"""

import os

from .value_parse import parse_number

# A value file holds a number. Read enough to find one and no more, so a
# runaway writer can't pull megabytes into memory on every tick.
_MAX_READ = 4096


def stat_mtime_ns(path: str | None) -> int | None:
    """Return the mtime of ``path`` in nanoseconds, or None.

    Cheaper than reading, so the tick can ask "has this changed?" once a
    second without opening a file that may live on slow storage.
    """
    if not path:
        return None
    try:
        return os.stat(os.path.expanduser(path)).st_mtime_ns
    except OSError:
        return None


def read_value_file(path: str | None) -> tuple[float | None, int | None]:
    """Return ``(value, mtime_ns)`` for the value file at ``path``.

    ``value`` is None when there is no path, the file can't be read, or it
    holds no number. ``mtime_ns`` is None only when the file can't be
    stat'd at all -- an unreadable-but-present file still reports its mtime
    so a caller can avoid re-reading it on every tick.
    """
    if not path:
        return None, None

    path = os.path.expanduser(path)
    try:
        # stat before reading: if the file changes mid-read we report the
        # older mtime, so the next tick sees a change and re-reads. Stat'ing
        # afterwards would record the newer mtime against older contents and
        # lose that write entirely.
        mtime_ns = os.stat(path).st_mtime_ns
    except OSError:
        return None, None

    try:
        with open(path, "r") as handle:
            text = handle.read(_MAX_READ)
    except OSError:
        return None, mtime_ns

    return parse_number(text), mtime_ns


def written_since(
    file_ns: int | None, started_ns: int | None
) -> bool:
    """True when the value file was written at or after ``started_ns``.

    Distinguishes a file that is *reporting* something from a file that
    merely still holds the number it held before. Without this, a command
    that prints nothing and doesn't touch the file would hand back the old
    value and undo the step the user just made.
    """
    if file_ns is None or started_ns is None:
        return False
    return file_ns >= started_ns


def pick_newer(
    stdout_value: float | None,
    stdout_ns: int | None,
    file_value: float | None,
    file_ns: int | None,
) -> float | None:
    """Return whichever of the two reported values is more recent.

    ``stdout_ns`` is when the command returned; ``file_ns`` is the value
    file's mtime. Both come from the same nanosecond clock domain, so the
    comparison is meaningful well below a millisecond.

    A tie goes to stdout -- the command is the thing we just deliberately
    ran. A value whose timestamp is missing can't win a comparison but is
    still preferred over nothing.
    """
    if file_value is None:
        return stdout_value
    if stdout_value is None:
        return file_value
    if file_ns is None:
        return stdout_value
    if stdout_ns is None:
        return file_value
    return file_value if file_ns > stdout_ns else stdout_value
