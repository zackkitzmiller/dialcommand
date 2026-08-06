import os

import pytest

from actions.DialCommand.value_source import (
    pick_newer,
    read_value_file,
    stat_mtime_ns,
    written_since,
)

# ── pick_newer ────────────────────────────────────────────────


@pytest.mark.unit
def test_file_wins_when_its_mtime_is_newer_than_the_command():
    assert pick_newer(10.0, 1_000, 20.0, 2_000) == 20.0


@pytest.mark.unit
def test_stdout_wins_when_the_command_finished_after_the_file_changed():
    assert pick_newer(10.0, 2_000, 20.0, 1_000) == 10.0


@pytest.mark.unit
def test_stdout_wins_a_tie():
    # Ties go to stdout: the command is the thing we just deliberately ran.
    assert pick_newer(10.0, 1_000, 20.0, 1_000) == 10.0


@pytest.mark.unit
def test_uses_whichever_side_reported_a_value():
    assert pick_newer(None, None, 20.0, 2_000) == 20.0
    assert pick_newer(10.0, 1_000, None, 2_000) == 10.0


@pytest.mark.unit
def test_returns_none_when_neither_side_reported():
    assert pick_newer(None, None, None, None) is None


@pytest.mark.unit
def test_falls_back_to_the_side_that_has_a_timestamp():
    # A value with no usable timestamp can't win a comparison, but it is
    # still better than nothing when the other side is empty.
    assert pick_newer(10.0, None, 20.0, 2_000) == 20.0
    assert pick_newer(10.0, 1_000, 20.0, None) == 10.0


# ── written_since ─────────────────────────────────────────────


@pytest.mark.unit
def test_a_file_written_during_the_command_counts_as_a_report():
    assert written_since(file_ns=2_000, started_ns=1_000) is True


@pytest.mark.unit
def test_a_file_untouched_since_before_the_command_does_not():
    # This is the stale-file case: the number was already there and was
    # already synced from. Treating it as a report would undo the step the
    # user just made.
    assert written_since(file_ns=500, started_ns=1_000) is False


@pytest.mark.unit
def test_a_write_landing_exactly_at_the_start_counts():
    assert written_since(file_ns=1_000, started_ns=1_000) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "file_ns,started_ns", [(None, 1_000), (2_000, None), (None, None)]
)
def test_no_report_without_both_timestamps(file_ns, started_ns):
    assert written_since(file_ns, started_ns) is False


# ── read_value_file ───────────────────────────────────────────


@pytest.mark.unit
def test_reads_a_number_and_an_mtime(tmp_path):
    f = tmp_path / "value"
    f.write_text("45\n")
    value, mtime_ns = read_value_file(str(f))
    assert value == 45.0
    assert mtime_ns == os.stat(f).st_mtime_ns


@pytest.mark.unit
@pytest.mark.parametrize(
    "contents,expected",
    [("45", 45.0), ("45%\n", 45.0), ("Volume: 45", 45.0), ("0.5", 0.5)],
)
def test_tolerates_the_shapes_scripts_actually_write(
    tmp_path, contents, expected
):
    f = tmp_path / "value"
    f.write_text(contents)
    assert read_value_file(str(f))[0] == expected


@pytest.mark.unit
def test_expands_a_tilde_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "value").write_text("7")
    assert read_value_file("~/value")[0] == 7.0


@pytest.mark.unit
@pytest.mark.parametrize("path", ["", None])
def test_returns_nothing_when_no_path_is_configured(path):
    assert read_value_file(path) == (None, None)


@pytest.mark.unit
def test_returns_nothing_when_the_file_is_missing(tmp_path):
    assert read_value_file(str(tmp_path / "nope")) == (None, None)


@pytest.mark.unit
@pytest.mark.parametrize("contents", ["", "   \n", "muted"])
def test_reports_the_mtime_even_when_there_is_no_number(tmp_path, contents):
    # The caller records the mtime so it doesn't re-read an unusable file
    # on every tick.
    f = tmp_path / "value"
    f.write_text(contents)
    value, mtime_ns = read_value_file(str(f))
    assert value is None
    assert mtime_ns == os.stat(f).st_mtime_ns


@pytest.mark.unit
def test_reports_the_mtime_when_the_file_exists_but_cannot_be_read(tmp_path):
    # Same rule as an unparseable file: present but unusable still yields an
    # mtime, so the caller records it and stops retrying the failing open()
    # on every tick.
    f = tmp_path / "value"
    f.write_text("45")
    f.chmod(0o000)
    try:
        value, mtime_ns = read_value_file(str(f))
        assert value is None
        assert mtime_ns == os.stat(f).st_mtime_ns
    finally:
        f.chmod(0o644)


# ── stat_mtime_ns ─────────────────────────────────────────────


@pytest.mark.unit
def test_stat_returns_the_mtime_of_an_existing_file(tmp_path):
    f = tmp_path / "value"
    f.write_text("45")
    assert stat_mtime_ns(str(f)) == os.stat(f).st_mtime_ns


@pytest.mark.unit
def test_stat_sees_a_rewrite_as_a_new_mtime(tmp_path):
    f = tmp_path / "value"
    f.write_text("45")
    first = stat_mtime_ns(str(f))
    f.write_text("46")
    assert stat_mtime_ns(str(f)) != first


@pytest.mark.unit
def test_stat_expands_a_tilde_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "value").write_text("7")
    assert stat_mtime_ns("~/value") == os.stat(tmp_path / "value").st_mtime_ns


@pytest.mark.unit
@pytest.mark.parametrize("path", ["", None])
def test_stat_returns_none_without_a_path(path):
    assert stat_mtime_ns(path) is None


@pytest.mark.unit
def test_stat_returns_none_for_a_missing_file(tmp_path):
    assert stat_mtime_ns(str(tmp_path / "nope")) is None


@pytest.mark.unit
def test_does_not_read_an_unbounded_amount(tmp_path):
    # A runaway writer must not pull megabytes into memory every tick.
    f = tmp_path / "value"
    f.write_text("9" * 5_000_000)
    value, _ = read_value_file(str(f))
    assert value is not None
