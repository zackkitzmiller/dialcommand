"""Editable threshold list widget for DialCommand.

A threshold maps a dial value onto a background color and an icon. The active
threshold is the one with the greatest ``at`` that is still <= the current
value, so the dial's appearance changes as it is turned across the range.

Each threshold is a plain dict so the whole list serializes straight into the
action settings::

    {"at": <number>, "color": [r, g, b, a], "icon": "<path or ''>"}

The widget owns no persistence itself: it calls ``on_change`` with a fresh copy
of the list whenever anything is edited, and the action stores it.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Gdk, Adw, Gio


def color_to_rgba(color: list[int]) -> Gdk.RGBA:
    """Convert a stored [r, g, b, a] (0-255) list into a Gdk.RGBA (0-1)."""
    rgba = Gdk.RGBA()
    r, g, b, a = (list(color) + [0, 0, 0, 255])[:4]
    rgba.red = r / 255.0
    rgba.green = g / 255.0
    rgba.blue = b / 255.0
    rgba.alpha = a / 255.0
    return rgba


def rgba_to_color(rgba: Gdk.RGBA) -> list[int]:
    """Convert a Gdk.RGBA (0-1) into a stored [r, g, b, a] (0-255) list."""
    return [
        round(rgba.red * 255),
        round(rgba.green * 255),
        round(rgba.blue * 255),
        round(rgba.alpha * 255),
    ]


class ThresholdListRow:
    """Wraps an ``Adw.ExpanderRow`` that edits a list of thresholds."""

    def __init__(
        self,
        title: str,
        thresholds: list[dict],
        value_min: float,
        value_max: float,
        step: float,
        on_change,
    ):
        # Work on a copy so we never mutate the caller's list in place.
        self._thresholds = [dict(t) for t in (thresholds or [])]
        self._value_min = value_min
        self._value_max = value_max
        self._step = step
        self._on_change = on_change

        self.widget = Adw.ExpanderRow(
            title=title,
            subtitle="Background color + icon per value breakpoint",
        )

        add_button = Gtk.Button(
            icon_name="list-add-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text="Add threshold",
        )
        add_button.add_css_class("flat")
        add_button.connect("clicked", self._on_add_clicked)
        self.widget.add_suffix(add_button)

        self._rows: list[Adw.ActionRow] = []
        self._rebuild_rows()

    # ── bounds updates ────────────────────────────────────────

    def set_bounds(self, value_min: float, value_max: float, step: float):
        """Update spin-button limits when the action's range/step changes."""
        self._value_min = value_min
        self._value_max = value_max
        self._step = step
        for row in list(self._rows):
            spin = getattr(row, "_at_spin", None)
            if spin is not None:
                adj = spin.get_adjustment()
                adj.set_lower(value_min)
                adj.set_upper(value_max)
                adj.set_step_increment(step)

    # ── row construction ──────────────────────────────────────

    def _rebuild_rows(self):
        for row in self._rows:
            self.widget.remove(row)
        self._rows = []
        for index in range(len(self._thresholds)):
            row = self._build_row(index)
            self.widget.add_row(row)
            self._rows.append(row)

    def _build_row(self, index: int) -> Adw.ActionRow:
        threshold = self._thresholds[index]
        row = Adw.ActionRow(title=f"Threshold {index + 1}")

        # Value at which this threshold becomes active.
        adjustment = Gtk.Adjustment(
            value=float(threshold.get("at", self._value_min)),
            lower=self._value_min,
            upper=self._value_max,
            step_increment=self._step or 1,
            page_increment=1,
        )
        at_spin = Gtk.SpinButton(
            adjustment=adjustment,
            digits=self._digits(),
            valign=Gtk.Align.CENTER,
            tooltip_text="Active at this value and above",
        )
        at_spin.connect("value-changed", self._on_at_changed, index)
        row._at_spin = at_spin
        row.add_suffix(at_spin)

        # Background color for this threshold.
        color_button = Gtk.ColorButton(
            rgba=color_to_rgba(threshold.get("color", [0, 0, 0, 255])),
            use_alpha=True,
            valign=Gtk.Align.CENTER,
            tooltip_text="Background color",
        )
        color_button.connect("color-set", self._on_color_set, index)
        row.add_suffix(color_button)

        # Icon file for this threshold.
        icon_button = Gtk.Button(
            valign=Gtk.Align.CENTER,
            tooltip_text="Choose icon (image)",
        )
        icon_button._label = Gtk.Label()
        icon_button.set_child(icon_button._label)
        self._refresh_icon_label(icon_button, threshold.get("icon", ""))
        icon_button.connect("clicked", self._on_icon_clicked, index)
        row.add_suffix(icon_button)

        # Remove this threshold.
        remove_button = Gtk.Button(
            icon_name="user-trash-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text="Remove threshold",
        )
        remove_button.add_css_class("flat")
        remove_button.connect("clicked", self._on_remove_clicked, index)
        row.add_suffix(remove_button)

        return row

    def _digits(self) -> int:
        return 0 if float(self._step or 1).is_integer() else 2

    def _refresh_icon_label(self, button: Gtk.Button, path: str):
        import os

        button._label.set_text(os.path.basename(path) if path else "No icon")

    # ── signal handlers ───────────────────────────────────────

    def _on_add_clicked(self, _button):
        self._thresholds.append(
            {"at": self._value_min, "color": [0, 0, 0, 255], "icon": ""}
        )
        self._rebuild_rows()
        self._emit()

    def _on_remove_clicked(self, _button, index: int):
        if 0 <= index < len(self._thresholds):
            del self._thresholds[index]
            self._rebuild_rows()
            self._emit()

    def _on_at_changed(self, spin: Gtk.SpinButton, index: int):
        if 0 <= index < len(self._thresholds):
            self._thresholds[index]["at"] = spin.get_value()
            self._emit()

    def _on_color_set(self, button: Gtk.ColorButton, index: int):
        if 0 <= index < len(self._thresholds):
            self._thresholds[index]["color"] = rgba_to_color(button.get_rgba())
            self._emit()

    def _on_icon_clicked(self, button: Gtk.Button, index: int):
        dialog = Gtk.FileDialog(title="Choose Icon")

        image_filter = Gtk.FileFilter()
        image_filter.set_name("Images")
        for pattern in ("*.png", "*.jpg", "*.jpeg", "*.svg", "*.gif", "*.webp"):
            image_filter.add_pattern(pattern)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(image_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(image_filter)

        def _on_open(dlg, result):
            try:
                file = dlg.open_finish(result)
            except Exception:
                return  # user cancelled
            if file is None:
                return
            path = file.get_path()
            if 0 <= index < len(self._thresholds):
                self._thresholds[index]["icon"] = path
                self._refresh_icon_label(button, path)
                self._emit()

        dialog.open(button.get_root(), None, _on_open)

    # ── emit ──────────────────────────────────────────────────

    def _emit(self):
        if self._on_change is not None:
            self._on_change([dict(t) for t in self._thresholds])
