import os
import subprocess
import threading
import time

import gi
from loguru import logger as log

from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner
from src.backend.DeckManagement.InputIdentifier import Input

from GtkHelper.GenerativeUI.EntryRow import EntryRow
from GtkHelper.GenerativeUI.SpinRow import SpinRow
from GtkHelper.GenerativeUI.ColorButtonRow import ColorButtonRow
from GtkHelper.GenerativeUI.SwitchRow import SwitchRow

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw

from .ThresholdList import ThresholdListRow
from .value_parse import in_range, parse_number
from .value_source import (
    pick_newer,
    read_value_file,
    stat_mtime_ns,
    written_since,
)


def is_in_flatpak() -> bool:
    return os.path.isfile("/.flatpak-info")


def run_command_capture(command: str, timeout: float) -> str | None:
    """Run a shell command and return its stdout, or None.

    Uses subprocess.Popen directly (not multiprocessing.Process, which
    triggers a threading._after_fork crash on Python 3.12+ and makes the
    action fire only once).

    Waits at most ``timeout`` seconds. A command that outlives the timeout is
    NOT killed -- it is left running detached and drained on a daemon thread,
    so this stays safe for "launch something long-lived" commands; we simply
    report no value for those.
    """
    if not command:
        return None

    if is_in_flatpak():
        command = "flatpak-spawn --host " + command

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=os.path.expanduser("~"),
            text=True,
        )
    except Exception as e:
        log.error(f"DialCommand: failed to run command: {e}")
        return None

    try:
        stdout, _ = proc.communicate(timeout=timeout)
        return stdout
    except subprocess.TimeoutExpired:
        # Let it finish on its own; drain the pipe so it can't block on a
        # full buffer and can't linger as a zombie.
        threading.Thread(target=_drain, args=(proc,), daemon=True).start()
        return None
    except Exception as e:
        log.error(f"DialCommand: failed to read command output: {e}")
        return None


def _drain(proc: "subprocess.Popen"):
    try:
        proc.communicate()
    except Exception:
        pass


def _num(value, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _fmt(value: float) -> str:
    """Format a value as an int when whole, else a trimmed float."""
    value = float(value)
    return str(int(value)) if value.is_integer() else f"{value:g}"


# Default range / step, kept in one place.
DEFAULT_MIN = 0.0
DEFAULT_MAX = 100.0
DEFAULT_STEP = 1.0
TRANSPARENT = [0, 0, 0, 0]

# How long a turn/press command gets to print its value before we give up and
# fall back to the internal counter. Kept short so the dial stays responsive.
COMMAND_TIMEOUT = 0.5


class DialCommand(ActionCore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.has_configuration = True
        # Threshold list is a custom row; render it below the generated rows.
        self.put_custom_config_rows_below_gen_ui = True
        self.threshold_row: ThresholdListRow | None = None

        # Last value-file mtime we acted on. Lets on_tick skip the read when
        # nothing has written the file, and keeps a broken path from logging
        # once a second.
        self._seen_mtime_ns: int | None = None

        self._build_event_assigners()
        self._build_generative_ui()

    # ── event assigners ───────────────────────────────────────

    def _build_event_assigners(self):
        self.add_event_assigner(
            EventAssigner(
                id="turn_cw",
                ui_label="Turn Clockwise",
                default_events=[Input.Dial.Events.TURN_CW],
                callback=lambda data: self._on_turn(1),
            )
        )

        self.add_event_assigner(
            EventAssigner(
                id="turn_ccw",
                ui_label="Turn Counter-Clockwise",
                default_events=[Input.Dial.Events.TURN_CCW],
                callback=lambda data: self._on_turn(-1),
            )
        )

        self.add_event_assigner(
            EventAssigner(
                id="press",
                ui_label="Press",
                default_events=[Input.Dial.Events.DOWN],
                callback=lambda data: self._on_press(),
            )
        )

        # Also support keys so this action works on buttons too (press only).
        self.add_event_assigner(
            EventAssigner(
                id="key_down",
                ui_label="Key Down",
                default_events=[Input.Key.Events.DOWN],
                callback=lambda data: self._on_press(),
            )
        )

    # ── generated config rows ─────────────────────────────────

    def _build_generative_ui(self):
        self.cw_row = EntryRow(
            action_core=self,
            var_name="command_cw",
            default_value="",
            title="↻ Clockwise Command",
            on_change=self._on_config_change,
        )
        self.ccw_row = EntryRow(
            action_core=self,
            var_name="command_ccw",
            default_value="",
            title="↺ Counter-Clockwise Command",
            on_change=self._on_config_change,
        )
        self.press_row = EntryRow(
            action_core=self,
            var_name="command_press",
            default_value="",
            title="⏎ Press Command",
            on_change=self._on_config_change,
        )

        self.value_file_row = EntryRow(
            action_core=self,
            var_name="value_file",
            default_value="",
            title="Value File",
            on_change=self._on_value_file_change,
        )

        self.min_row = SpinRow(
            action_core=self,
            var_name="min",
            default_value=DEFAULT_MIN,
            min=-1_000_000,
            max=1_000_000,
            step=1,
            digits=2,
            title="Minimum Value",
            on_change=self._on_range_change,
        )
        self.max_row = SpinRow(
            action_core=self,
            var_name="max",
            default_value=DEFAULT_MAX,
            min=-1_000_000,
            max=1_000_000,
            step=1,
            digits=2,
            title="Maximum Value",
            on_change=self._on_range_change,
        )
        self.step_row = SpinRow(
            action_core=self,
            var_name="step",
            default_value=DEFAULT_STEP,
            min=0.001,
            max=1_000_000,
            step=1,
            digits=3,
            title="Step Size",
            on_change=self._on_range_change,
        )

        self.base_color_row = ColorButtonRow(
            action_core=self,
            var_name="base_color",
            default_value=tuple(TRANSPARENT),
            title="Base Background Color",
            on_change=self._on_config_change,
        )

        self.blend_row = SwitchRow(
            action_core=self,
            var_name="blend",
            default_value=False,
            title="Blend Colors",
            subtitle="Fade smoothly between thresholds instead of a hard swap",
            on_change=self._on_config_change,
        )

    def get_config_rows(self) -> "list[Adw.PreferencesRow]":
        self.threshold_row = ThresholdListRow(
            title="Thresholds",
            thresholds=self._get_thresholds(),
            value_min=self._min(),
            value_max=self._max(),
            step=self._step(),
            on_change=self._on_thresholds_change,
        )
        return [self.threshold_row.widget]

    # ── settings accessors ────────────────────────────────────

    def _min(self) -> float:
        return _num(self.get_settings().get("min", DEFAULT_MIN), DEFAULT_MIN)

    def _max(self) -> float:
        return _num(self.get_settings().get("max", DEFAULT_MAX), DEFAULT_MAX)

    def _step(self) -> float:
        return _num(self.get_settings().get("step", DEFAULT_STEP), DEFAULT_STEP)

    def _get_thresholds(self) -> list[dict]:
        return self.get_settings().get("thresholds", [])

    def _value_file(self) -> str:
        return str(self.get_settings().get("value_file", "") or "").strip()

    def _blend(self) -> bool:
        return bool(self.get_settings().get("blend", False))

    def _get_value(self) -> float:
        settings = self.get_settings()
        value = _num(settings.get("value", settings.get("min", DEFAULT_MIN)))
        return self._clamp(value)

    def _clamp(self, value: float) -> float:
        low, high = self._min(), self._max()
        if low > high:
            low, high = high, low
        return max(low, min(high, value))

    def _set_value(self, value: float) -> float:
        value = self._clamp(value)
        settings = self.get_settings()
        settings["value"] = value
        self.set_settings(settings)
        return value

    # ── value file ────────────────────────────────────────────

    def _accept(self, value: float | None, source: str) -> float | None:
        """Range-check a value reported by an outside source.

        Out-of-range is rejected rather than clamped, so a source reporting
        nonsense can't drag the dial to an end stop.
        """
        if value is None:
            return None
        low, high = self._min(), self._max()
        if not in_range(value, low, high):
            log.warning(
                f"DialCommand: ignoring {source} value {_fmt(value)}, "
                f"outside range {_fmt(low)}..{_fmt(high)}"
            )
            return None
        return value

    def _read_file_value(self) -> tuple[float | None, int | None]:
        """Current (value, mtime_ns) from the configured value file."""
        value, mtime_ns = read_value_file(self._value_file())
        return self._accept(value, "value file"), mtime_ns

    def _sync_from_file(self) -> bool:
        """Adopt the value file's number. True when the value changed."""
        if not self._value_file():
            return False
        value, mtime_ns = self._read_file_value()
        self._seen_mtime_ns = mtime_ns
        if value is None or value == self._get_value():
            return False
        self._set_value(value)
        return True

    # ── event handlers ────────────────────────────────────────

    def on_tick(self):
        """Poll the value file so outside changes reach the dial face.

        Runs about once a second for actions on the active page. Stats before
        reading, and only does real work when the file has actually moved.
        """
        try:
            path = self._value_file()
            if not path:
                return
            if stat_mtime_ns(path) == self._seen_mtime_ns:
                return
            if self._sync_from_file():
                self._update_visuals()
        except Exception as e:
            log.error(f"DialCommand: value file tick failed: {e}")

    def _on_turn(self, direction: int):
        # Re-base on the value file first, so the step is relative to reality
        # rather than to a counter that drifted while we weren't looking.
        self._sync_from_file()
        step = self._step()
        # The stepped value is only what we *ask* for; what the command and
        # the value file report is what we believe afterwards.
        proposed = self._set_value(self._get_value() + direction * step)
        cmd = "command_cw" if direction > 0 else "command_ccw"
        reported = self._run_with_value(self.get_settings().get(cmd), proposed)
        if reported is not None:
            self._set_value(reported)
        self._update_visuals()

    def _on_press(self):
        self._sync_from_file()
        reported = self._run_with_value(
            self.get_settings().get("command_press"), self._get_value()
        )
        if reported is not None:
            self._set_value(reported)
        self._update_visuals()

    def _run_with_value(self, command: str, value: float) -> float | None:
        """Run ``command`` with {value} substituted; return what it reported.

        A command can report back two ways: by printing a number, or by
        writing the configured value file. When both happen, the more recent
        one wins -- so a command that outlives COMMAND_TIMEOUT can still be
        heard through the file, and an unrelated process that touched the
        file mid-command isn't overwritten by a staler number.

        None means nothing usable came back -- no output, no number, nothing
        in range -- and the caller should keep its own bookkeeping.
        """
        if not command:
            return None

        started_ns = time.time_ns()
        stdout = run_command_capture(
            command.replace("{value}", _fmt(value)), COMMAND_TIMEOUT
        )
        stdout_ns = time.time_ns()
        stdout_value = self._accept(parse_number(stdout), "reported")

        # Read the file *after* the command, not before: the point is to see
        # anything it (or anyone else) wrote while it was running.
        file_value, file_ns = self._read_file_value()
        if self._value_file():
            self._seen_mtime_ns = file_ns

        # An untouched file isn't reporting anything -- it still holds the
        # number we already synced from at the start of the turn. Taking it
        # here would undo the step the user just made.
        if not written_since(file_ns, started_ns):
            file_value = None

        return pick_newer(stdout_value, stdout_ns, file_value, file_ns)

    # ── config change handlers ────────────────────────────────

    def _on_config_change(self, *_args):
        self._update_visuals()

    def _on_value_file_change(self, *_args):
        # Forget the old file's mtime so the new path is read immediately
        # rather than after it happens to change.
        self._seen_mtime_ns = None
        self._sync_from_file()
        self._update_visuals()

    def _on_range_change(self, *_args):
        # Re-clamp the current value and keep the threshold editor in sync.
        self._set_value(self._get_value())
        if self.threshold_row is not None:
            self.threshold_row.set_bounds(
                self._min(), self._max(), self._step()
            )
        self._update_visuals()

    def _on_thresholds_change(self, thresholds: list[dict]):
        settings = self.get_settings()
        settings["thresholds"] = thresholds
        self.set_settings(settings)
        self._update_visuals()

    # ── visuals ───────────────────────────────────────────────

    def _active_threshold(self, value: float) -> dict | None:
        matches = [
            t for t in self._get_thresholds() if _num(t.get("at")) <= value
        ]
        if not matches:
            return None
        return max(matches, key=lambda t: _num(t.get("at")))

    def _default_icon(self) -> str:
        return os.path.join(self.plugin_base.PATH, "assets", "dial.png")

    def _rgba(self, color) -> list[int]:
        """Normalize any stored color into a 4-channel [r, g, b, a] list."""
        return (list(color) + [0, 0, 0, 255])[:4]

    def _color_stops(self) -> list[tuple[float, list[int]]]:
        """Sorted (at, rgba) breakpoints used for blending.

        The base color, when opaque, acts as the floor stop at ``min`` so the
        fade starts from it rather than snapping to the first threshold.
        """
        stops: list[tuple[float, list[int]]] = []
        base = self._rgba(self.get_settings().get("base_color", TRANSPARENT))
        if base[3] > 0:
            stops.append((self._min(), base))
        for t in self._get_thresholds():
            color = t.get("color")
            if color:
                stops.append((_num(t.get("at")), self._rgba(color)))
        stops.sort(key=lambda s: s[0])
        return stops

    def _blended_color(self, value: float) -> list[int] | None:
        """Linearly interpolate the color across the sorted stops."""
        stops = self._color_stops()
        if not stops:
            return None
        if value <= stops[0][0]:
            return list(stops[0][1])
        if value >= stops[-1][0]:
            return list(stops[-1][1])
        for (lo_at, lo_c), (hi_at, hi_c) in zip(stops, stops[1:]):
            if lo_at <= value <= hi_at:
                span = hi_at - lo_at
                f = 0.0 if span == 0 else (value - lo_at) / span
                return [
                    round(lo_c[i] + (hi_c[i] - lo_c[i]) * f) for i in range(4)
                ]
        return list(stops[-1][1])

    def _resolve_color(self, value: float) -> list[int] | None:
        """The color the plugin wants to paint, or None to fall back."""
        if self._blend():
            return self._blended_color(value)
        threshold = self._active_threshold(value)
        if threshold and threshold.get("color"):
            color = list(threshold["color"])
            if len(color) >= 4 and color[3] > 0:
                return color
        base = list(self.get_settings().get("base_color", TRANSPARENT))
        if len(base) >= 4 and base[3] > 0:
            return base
        return None

    def _configured_page_color(self) -> list[int] | None:
        """The input's own background color as saved on the page.

        Read from the page config (not the live manager) so it always
        reflects the user's real setting, never a runtime override of ours.
        """
        try:
            cfg = self.input_ident.get_config(self.page)
            return (
                cfg.get("states", {})
                .get(str(self.state), {})
                .get("background", {})
                .get("color", None)
            )
        except Exception:
            return None

    def _update_visuals(self):
        try:
            value = self._get_value()

            # StreamController renders the input's page/background color in
            # preference to any action color, so drive the page color directly
            # and restore the user's configured color when we have nothing to
            # show.
            resolved = self._resolve_color(value)
            configured = self._configured_page_color()
            color = (
                resolved
                if resolved is not None
                else (configured or TRANSPARENT)
            )

            # Set the icon and label first without rendering, then drive the
            # page color last with update=True. set_label's own update path
            # bails on the label-control guard, so it can't be relied on to
            # repaint; set_page_color(update=True) always reaches
            # ControllerDial.update() and repaints the touch
            # strip on every turn.
            # The value goes on the bottom label; set_label no-ops when the
            # user hasn't given this action control of that label.
            threshold = self._active_threshold(value)
            icon = threshold.get("icon") if threshold else None
            if icon and os.path.isfile(icon):
                self.set_media(media_path=icon, update=False)
            else:
                self.set_media(media_path=self._default_icon(), update=False)

            self.set_label(_fmt(value), position="bottom", update=False)

            state = self.get_state()
            if state is not None:
                state.background_manager.set_page_color(
                    list(color), update=True
                )
        except Exception as e:
            log.error(f"DialCommand: failed to update visuals: {e}")

    # ── lifecycle ─────────────────────────────────────────────

    def on_ready(self):
        # Prefer the value file's number over the persisted one: something
        # may have moved it while this page wasn't loaded.
        self._sync_from_file()
        # Clamp any persisted value into the current range, then paint.
        self._set_value(self._get_value())
        self._update_visuals()
