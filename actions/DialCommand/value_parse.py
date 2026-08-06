"""Pure helpers for turning command output into a numeric dial value.

Kept free of gi / StreamController imports so it can be unit tested on its
own.
"""

import re

_NUMBER = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_number(text: str | None) -> float | None:
    """Return the first number found in ``text``, or None.

    Tolerates the shapes real scripts print: ``45``, ``45%``, ``0.45``,
    ``Volume: 45``, ``45 dB``. Returns None when there is no number at all,
    so the caller can fall back to its own bookkeeping.
    """
    if not text:
        return None
    match = _NUMBER.search(text)
    if match is None:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def in_range(value: float, low: float, high: float) -> bool:
    """True when ``value`` sits inside the inclusive ``low``..``high`` range.

    Tolerates bounds saved the wrong way round (max below min) by sorting
    them first, matching how the action clamps.
    """
    if low > high:
        low, high = high, low
    return low <= value <= high
