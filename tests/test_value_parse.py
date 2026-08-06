import pytest

from actions.DialCommand.value_parse import in_range, parse_number


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected",
    [
        ("45", 45.0),
        ("45\n", 45.0),
        ("45%", 45.0),
        ("0.45", 0.45),
        (".5", 0.5),
        ("-3", -3.0),
        ("Volume: 45", 45.0),
        ("45 dB", 45.0),
        ("  72  \n", 72.0),
        ("1e2", 100.0),
        ("12\n34\n", 12.0),
    ],
)
def test_parses_first_number_from_command_output(text, expected):
    assert parse_number(text) == expected


@pytest.mark.unit
@pytest.mark.parametrize("text", ["", None, "   \n", "muted", "n/a"])
def test_returns_none_when_output_has_no_number(text):
    assert parse_number(text) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,low,high",
    [
        (0.0, 0.0, 100.0),  # on the lower bound
        (100.0, 0.0, 100.0),  # on the upper bound
        (45.0, 0.0, 100.0),
        (-3.0, -10.0, 10.0),
        (0.5, 0.0, 1.0),
        (5.0, 10.0, 0.0),  # bounds saved backwards
        (7.0, 7.0, 7.0),  # degenerate range
    ],
)
def test_in_range_accepts_values_inside_the_configured_range(value, low, high):
    assert in_range(value, low, high) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,low,high",
    [
        (101.0, 0.0, 100.0),
        (-1.0, 0.0, 100.0),
        (0.0001, 1.0, 10.0),
        (-11.0, -10.0, 10.0),
        (11.0, 10.0, 0.0),  # bounds saved backwards
        (8.0, 7.0, 7.0),  # degenerate range
    ],
)
def test_in_range_rejects_values_outside_the_configured_range(value, low, high):
    assert in_range(value, low, high) is False
