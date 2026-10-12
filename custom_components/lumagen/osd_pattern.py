"""Volume OSD pattern builder for the Lumagen on-screen display.

Pure functions with no Home Assistant dependency.  A :class:`VolumePattern`
describes the layout; :func:`render_volume` turns a value into the text sent
with ``ZT`` (2 lines x 30 characters, legal characters 0x20-0x7A).

Solid bars use the Lumagen's ``ZB`` command, which renders one chosen
character as a solid block.  The renderer emits a placeholder for solid cells
and picks a block character that does not appear anywhere else in the message.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any, Literal, get_args

from .client import pick_block_char

OSD_WIDTH = 30

Lines = Literal[1, 2]
BarType = Literal["none", "left_to_right", "center_out"]
Placement = Literal["left", "center", "right"]
ValueDisplay = Literal["raw", "percent", "linear"]
MuteDisplay = Literal["text", "empty_bar", "none"]

BAR_TYPES: tuple[str, ...] = get_args(BarType)
PLACEMENTS: tuple[str, ...] = get_args(Placement)
VALUE_DISPLAYS: tuple[str, ...] = get_args(ValueDisplay)
MUTE_DISPLAYS: tuple[str, ...] = get_args(MuteDisplay)

SOLID = "solid"
SOLID_GLYPH = "\u2588"  # used only in previews
_SOLID_MARK = "\x00"  # internal placeholder for solid cells

# End-cap choices offered in the UI ("" = none).  Any two legal characters
# are accepted.
END_CAP_CHOICES: tuple[str, ...] = ("", "[]", "<>", "()")


def is_legal_osd_text(text: str) -> bool:
    """True if every character is in the Lumagen OSD range (0x20-0x7A)."""
    return all(0x20 <= ord(c) <= 0x7A for c in text)


@dataclass(frozen=True)
class VolumePattern:
    """User-configurable volume display pattern."""

    lines: int = 1
    bar_type: str = "left_to_right"
    value_placement: str = "left"
    bar_width: int = 0  # 0 = fill remaining space
    fill_char: str = SOLID  # "solid" or one legal character
    empty_char: str = "-"  # "" = none (blank cells)
    end_caps: str = "[]"  # "" = none, else exactly two characters
    label: str = "Volume"
    value_suffix: str = ""  # text right after the value, e.g. "%", " dB", " -"
    value_display: str = "raw"  # raw | percent | linear
    value_scale: float = 1.0  # linear: shown = value * scale + offset
    value_offset: float = 0.0
    decimals: int = 0
    min_max_text: bool = False  # show "Min" / "Max" at the ends
    mute_display: str = "text"
    mute_text: str = "- MUTE -"
    mute_persist: bool = True
    duration: int = 1  # seconds, 1-8

    # -- validation ---------------------------------------------------------

    def errors(self) -> dict[str, str]:
        """Return {field: message} for invalid settings (empty when valid)."""
        err: dict[str, str] = {}
        if self.lines not in (1, 2):
            err["lines"] = "must be 1 or 2"
        if self.bar_type not in BAR_TYPES:
            err["bar_type"] = f"must be one of {', '.join(BAR_TYPES)}"
        if self.value_placement not in PLACEMENTS:
            err["value_placement"] = f"must be one of {', '.join(PLACEMENTS)}"
        if not 0 <= self.bar_width <= OSD_WIDTH:
            err["bar_width"] = f"must be 0-{OSD_WIDTH}"
        if self.fill_char != SOLID and (
            len(self.fill_char) != 1 or not is_legal_osd_text(self.fill_char)
        ):
            err["fill_char"] = "must be 'solid' or one character (space to z)"
        if len(self.empty_char) > 1 or not is_legal_osd_text(self.empty_char):
            err["empty_char"] = "must be empty or one character (space to z)"
        if self.end_caps and (
            len(self.end_caps) != 2 or not is_legal_osd_text(self.end_caps)
        ):
            err["end_caps"] = "must be empty or exactly two characters"
        for name in ("label", "value_suffix", "mute_text"):
            value = getattr(self, name)
            if not is_legal_osd_text(value):
                err[name] = "only characters from space to z are allowed"
            elif len(value) > OSD_WIDTH:
                err[name] = f"must be at most {OSD_WIDTH} characters"
        if self.value_display not in VALUE_DISPLAYS:
            err["value_display"] = f"must be one of {', '.join(VALUE_DISPLAYS)}"
        if not 0 <= self.decimals <= 2:
            err["decimals"] = "must be 0-2"
        if self.mute_display not in MUTE_DISPLAYS:
            err["mute_display"] = f"must be one of {', '.join(MUTE_DISPLAYS)}"
        if not 1 <= self.duration <= 8:
            err["duration"] = "must be 1-8"
        return err

    # -- (de)serialization --------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VolumePattern:
        """Build from a dict, ignoring unknown keys and coercing types."""
        kwargs: dict[str, Any] = {}
        defaults = cls()
        for f in fields(cls):
            if f.name not in data or data[f.name] is None:
                continue
            value = data[f.name]
            default = getattr(defaults, f.name)
            if isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, int):
                value = int(value)
            elif isinstance(default, float):
                value = float(value)
            else:
                value = str(value)
            kwargs[f.name] = value
        return cls(**kwargs)


@dataclass(frozen=True)
class OsdFrame:
    """Rendered OSD message."""

    line_one: str
    line_two: str = ""
    block_char: str = ""  # character remapped to a solid block via ZB
    duration: int = 1  # 1-8 seconds, 0 = persistent

    def preview(self) -> str:
        """Human-readable preview (solid cells shown as a block glyph)."""
        out = [self.line_one, self.line_two] if self.line_two else [self.line_one]
        if self.block_char:
            out = [ln.replace(self.block_char, SOLID_GLYPH) for ln in out]
        return "\n".join(out)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fraction(value: float, minimum: float, maximum: float) -> float:
    if maximum <= minimum:
        return 0.0
    return max(0.0, min(1.0, (value - minimum) / (maximum - minimum)))


def format_value(
    pattern: VolumePattern, value: float, minimum: float, maximum: float
) -> str:
    """Format the numeric part of the display (without label/suffix)."""
    frac = _fraction(value, minimum, maximum)
    if pattern.min_max_text:
        if frac <= 0.0:
            return "Min"
        if frac >= 1.0:
            return "Max"
    if pattern.value_display == "percent":
        shown = frac * 100.0
    elif pattern.value_display == "linear":
        shown = value * pattern.value_scale + pattern.value_offset
    else:
        shown = value
    text = f"{shown:.{pattern.decimals}f}"
    if text.startswith("-") and float(text) == 0:
        text = text[1:]  # avoid "-0"
    return text


def _text_block(pattern: VolumePattern, value_text: str) -> str:
    label = pattern.label
    if label and value_text and not label.endswith(" "):
        label += " "
    return f"{label}{value_text}{pattern.value_suffix}"


def _reserved_width(pattern: VolumePattern, minimum: float, maximum: float) -> int:
    """Widest value block over the range, so the bar doesn't shift as digits change."""
    samples = (
        minimum,
        maximum,
        (minimum + maximum) / 2,
        minimum + (maximum - minimum) * 0.99,
    )
    return max(
        len(_text_block(pattern, format_value(pattern, v, minimum, maximum)))
        for v in samples
    )


def _fit(block: str, width: int, placement: str) -> str:
    """Pad *block* to *width*, aligned toward the bar-facing side."""
    if len(block) >= width:
        return block
    if placement == "right":
        return block.rjust(width)
    if placement == "center":
        return block.center(width)
    return block.ljust(width)


def _cells(width: int, filled: int, fill: str, empty: str) -> str:
    filled = max(0, min(width, filled))
    return fill * filled + empty * (width - filled)


def _place(text: str, placement: str, width: int = OSD_WIDTH) -> str:
    text = text[:width]
    if placement == "center":
        pad = (width - len(text)) // 2
        return " " * pad + text
    if placement == "right":
        return text.rjust(width)
    return text


def _bar_left_to_right(width: int, frac: float, fill: str, empty: str) -> str:
    return _cells(width, round(frac * width), fill, empty)


def _bar_center_out(width: int, frac: float, fill: str, empty: str) -> str:
    """Bar growing outward from the middle of *width* cells."""
    half = width // 2
    n = round(frac * half)
    left = empty * (half - n) + fill * n
    right = fill * n + empty * (half - n)
    middle = ""
    if width % 2:
        middle = fill if frac > 0 else empty
    return left + middle + right


def _render_one_line(
    pattern: VolumePattern,
    block: str,
    frac: float,
    fill: str,
    empty: str,
    reserve: int = 0,
) -> str:
    caps_l, caps_r = (
        (pattern.end_caps[0], pattern.end_caps[1]) if pattern.end_caps else ("", "")
    )
    caps = len(caps_l) + len(caps_r)

    if pattern.bar_type == "none":
        return _place(block, pattern.value_placement)

    if pattern.bar_type == "center_out":
        # Value sits in the middle; bar halves grow outward from it.  The value
        # is not padded: spare width (when it has fewer digits than the widest
        # value) becomes extra empty cells at the outer ends, so the bar always
        # touches the value and the outer ends never move.
        reserve = max(reserve, len(block))
        gap = 2 if block else 0  # one space either side of the value
        room = OSD_WIDTH - caps - reserve - gap
        side = room // 2
        if pattern.bar_width:
            side = min(side, max(1, (pattern.bar_width - reserve - gap) // 2))
        side = max(0, side)
        extra = reserve - len(block)
        extra_l, extra_r = extra // 2, extra - extra // 2
        n = round(frac * side)
        left = empty * (side - n + extra_l) + fill * n
        right = fill * n + empty * (side - n + extra_r)
        mid = f" {block} " if block else ""
        return _place(f"{caps_l}{left}{mid}{right}{caps_r}", "center")

    # left_to_right
    gap = 1 if block else 0
    room = OSD_WIDTH - caps - len(block) - gap
    if pattern.value_placement == "center":
        room = OSD_WIDTH - caps - len(block) - (2 if block else 0)
    width = min(room, pattern.bar_width) if pattern.bar_width else room
    width = max(1, width)

    if pattern.value_placement == "center":
        # value embedded in the middle; fill runs left part then right part
        left_w = width // 2
        right_w = width - left_w
        filled = round(frac * width)
        left = _cells(left_w, filled, fill, empty)
        right = _cells(right_w, filled - left_w, fill, empty)
        mid = f" {block} " if block else ""
        return f"{caps_l}{left}{mid}{right}{caps_r}"

    bar = f"{caps_l}{_bar_left_to_right(width, frac, fill, empty)}{caps_r}"
    if not block:
        return bar
    if pattern.value_placement == "right":
        return f"{bar} {block}"
    return f"{block} {bar}"


def _render_bar_line(pattern: VolumePattern, frac: float, fill: str, empty: str) -> str:
    caps_l, caps_r = (
        (pattern.end_caps[0], pattern.end_caps[1]) if pattern.end_caps else ("", "")
    )
    room = OSD_WIDTH - len(caps_l) - len(caps_r)
    width = min(room, pattern.bar_width) if pattern.bar_width else room
    width = max(1, width)
    if pattern.bar_type == "center_out":
        bar = _bar_center_out(width, frac, fill, empty)
    else:
        bar = _bar_left_to_right(width, frac, fill, empty)
    line = f"{caps_l}{bar}{caps_r}"
    if pattern.bar_width and pattern.bar_type == "center_out":
        return _place(line, "center")
    return line


def _finish(line_one: str, line_two: str, duration: int) -> OsdFrame:
    line_one = line_one[:OSD_WIDTH]
    line_two = line_two[:OSD_WIDTH]
    block_char = ""
    if _SOLID_MARK in line_one + line_two:
        block_char = pick_block_char((line_one + line_two).replace(_SOLID_MARK, ""))
        line_one = line_one.replace(_SOLID_MARK, block_char)
        line_two = line_two.replace(_SOLID_MARK, block_char)
    return OsdFrame(
        line_one=line_one.rstrip(),
        line_two=line_two.rstrip(),
        block_char=block_char,
        duration=duration,
    )


def render_volume(
    pattern: VolumePattern,
    value: float | None,
    *,
    minimum: float = 0.0,
    maximum: float = 100.0,
    muted: bool = False,
) -> OsdFrame | None:
    """Render the volume (or mute) display.

    Returns None when nothing should be shown (e.g. muted with
    ``mute_display="none"``, or no value).
    """
    fill = _SOLID_MARK if pattern.fill_char == SOLID else pattern.fill_char
    empty = pattern.empty_char or " "

    if muted:
        if pattern.mute_display == "none":
            return None
        duration = 0 if pattern.mute_persist else pattern.duration
        if pattern.mute_display == "text" or pattern.bar_type == "none":
            return _finish(
                _place(pattern.mute_text, pattern.value_placement), "", duration
            )
        # empty bar with the mute text in place of the value
        label = pattern.label
        if label and not label.endswith(" "):
            label += " "
        block = f"{label}{pattern.mute_text}".strip()
        frac = 0.0
    else:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        frac = _fraction(value, minimum, maximum)
        block = _text_block(pattern, format_value(pattern, value, minimum, maximum))
        duration = pattern.duration

    reserve = 0
    if pattern.bar_type != "none" and pattern.lines == 1:
        reserve = _reserved_width(pattern, minimum, maximum)
        if pattern.bar_type != "center_out":
            block = _fit(block, reserve, pattern.value_placement)

    if pattern.lines == 2 and pattern.bar_type != "none":
        line_one = _place(block, pattern.value_placement)
        line_two = _render_bar_line(pattern, frac, fill, empty)
    else:
        line_one = _render_one_line(pattern, block, frac, fill, empty, reserve)
        line_two = ""
    return _finish(line_one, line_two, duration)


def preview_samples(
    pattern: VolumePattern, minimum: float = 0.0, maximum: float = 100.0
) -> str:
    """Markdown-ready preview at min, ~42%, max and muted."""
    out: list[str] = []
    mid = minimum + (maximum - minimum) * 0.42
    samples: list[tuple[str, float | None, bool]] = [
        ("min", minimum, False),
        ("42%", mid, False),
        ("max", maximum, False),
        ("muted", None, True),
    ]
    for name, value, muted in samples:
        frame = render_volume(
            pattern, value, minimum=minimum, maximum=maximum, muted=muted
        )
        text = frame.preview() if frame else "(nothing shown)"
        body = "\n".join(f"|{ln:<{OSD_WIDTH}}|" for ln in text.split("\n"))
        out.append(f"{name}:\n{body}")
    return "\n".join(out)
