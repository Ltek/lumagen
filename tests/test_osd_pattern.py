"""Tests for the volume OSD pattern builder."""

from __future__ import annotations

import itertools

import pytest

from custom_components.lumagen.osd_pattern import (
    OSD_WIDTH,
    SOLID,
    VolumePattern,
    format_value,
    pick_block_char,
    preview_samples,
    render_volume,
)


def _render(
    pattern: VolumePattern, value: float, *, maximum: float = 100.0
) -> tuple[str, str, str]:
    frame = render_volume(pattern, value, maximum=maximum)
    assert frame is not None
    return frame.line_one, frame.line_two, frame.block_char


class TestAllCombinations:
    def test_every_combination_fits_and_is_legal(self):
        combos = itertools.product(
            (1, 2),
            ("none", "left_to_right", "center_out"),
            ("left", "center", "right"),
            (0, 12),
            (SOLID, "="),
            ("", "-"),
            ("", "[]"),
            ("Volume", ""),
        )
        for lines, bar, place, width, fill, empty, caps, label in combos:
            p = VolumePattern(
                lines=lines,
                bar_type=bar,
                value_placement=place,
                bar_width=width,
                fill_char=fill,
                empty_char=empty,
                end_caps=caps,
                label=label,
                value_suffix=" dB",
            )
            assert not p.errors()
            for value in (0, 7, 42, 99.5, 100, 150, -5):
                frame = render_volume(p, value)
                assert frame is not None
                for line in (frame.line_one, frame.line_two):
                    assert len(line) <= OSD_WIDTH, (p, value, line)
                    assert all(0x20 <= ord(c) <= 0x7A for c in line), line
                if frame.block_char:
                    assert fill == SOLID


class TestLayouts:
    def test_text_only_matches_users_automation(self):
        p = VolumePattern(bar_type="none", label="- Volume", value_suffix=" -")
        assert _render(p, 42) == ("- Volume 42 -", "", "")

    def test_mute_text(self):
        p = VolumePattern(bar_type="none")
        frame = render_volume(p, None, muted=True)
        assert frame is not None
        assert frame.line_one == "- MUTE -"
        assert frame.duration == 0  # persists until unmuted

    def test_mute_with_timeout(self):
        p = VolumePattern(mute_persist=False, duration=3)
        frame = render_volume(p, None, muted=True)
        assert frame is not None
        assert frame.duration == 3

    def test_mute_none_shows_nothing(self):
        assert render_volume(VolumePattern(mute_display="none"), 5, muted=True) is None

    def test_mute_empty_bar(self):
        p = VolumePattern(mute_display="empty_bar", fill_char="=", mute_text="MUTE")
        frame = render_volume(p, None, muted=True)
        assert frame is not None
        assert "Volume MUTE" in frame.line_one
        assert "=" not in frame.line_one
        assert "[" in frame.line_one

    def test_left_to_right_fill_proportion(self):
        p = VolumePattern(
            label="", fill_char="#", empty_char="-", end_caps="", bar_width=10
        )
        line, _, _ = _render(p, 50)
        assert line.endswith("#####-----")

    def test_end_caps_and_empty_none(self):
        p = VolumePattern(label="", end_caps="", empty_char="", fill_char="=")
        line, _, _ = _render(p, 100)
        assert "[" not in line and "-" not in line

    def test_custom_end_caps(self):
        p = VolumePattern(label="", end_caps="{}"[0] + ">", fill_char="=")
        assert "end_caps" in p.errors()  # '{' is illegal on the OSD
        p = VolumePattern(label="", end_caps="<>", fill_char="=")
        line, _, _ = _render(p, 100)
        assert "<" in line and line.rstrip().endswith(">")

    def test_bar_does_not_shift_with_digit_count(self):
        p = VolumePattern()
        lines = [_render(p, v)[0] for v in (0, 5, 42, 100)]
        assert len({ln.index("[") for ln in lines}) == 1

    def test_center_out_symmetry(self):
        p = VolumePattern(
            bar_type="center_out", label="", end_caps="", fill_char="#", empty_char="-"
        )
        line, _, _ = _render(p, 50)
        left, _, right = line.strip().partition(" 50 ")
        assert left.count("#") == right.count("#")
        assert left.endswith("#") and right.startswith("#")  # grows from the value
        # outer ends may differ by one spare cell when the digit count is odd
        assert abs(len(left) - len(right)) <= 1

    def test_center_out_outer_ends_fixed(self):
        p = VolumePattern(bar_type="center_out", label="", end_caps="[]")
        lines = [_render(p, v)[0] for v in (0, 5, 42, 100)]
        assert len({ln.index("[") for ln in lines}) == 1
        assert len({ln.index("]") for ln in lines}) == 1

    def test_two_lines(self):
        p = VolumePattern(lines=2, end_caps="", empty_char=".")
        one, two, block = _render(p, 50)
        assert one == "Volume 50"
        assert len(two) == OSD_WIDTH
        assert two.count(block) == 15

    def test_right_placement(self):
        p = VolumePattern(value_placement="right", end_caps="", label="Vol")
        line, _, _ = _render(p, 42)
        assert line.endswith("Vol 42")

    def test_center_placement_bar_wraps_value(self):
        p = VolumePattern(value_placement="center", label="", fill_char="#")
        line, _, _ = _render(p, 100)
        assert line.startswith("[#") and line.endswith("#]")
        assert " 100 " in line


class TestValues:
    def test_percent(self):
        p = VolumePattern(value_display="percent", decimals=1)
        assert format_value(p, 0.635, 0, 1) == "63.5"

    def test_denon_db(self):
        p = VolumePattern(
            value_display="linear", value_scale=100, value_offset=-80, decimals=1
        )
        assert format_value(p, 0.635, 0, 1) == "-16.5"

    def test_no_negative_zero(self):
        p = VolumePattern(value_display="linear", value_offset=-0.4)
        assert format_value(p, 0, 0, 100) == "0"

    def test_min_max_text(self):
        p = VolumePattern(min_max_text=True)
        assert format_value(p, 0, 0, 100) == "Min"
        assert format_value(p, 100, 0, 100) == "Max"
        assert format_value(p, 50, 0, 100) == "50"

    def test_full_scale_clamps(self):
        p = VolumePattern(label="", end_caps="", fill_char="#", empty_char="-")
        line, _, _ = _render(p, 95, maximum=80)
        assert "-" not in line

    def test_nothing_without_value(self):
        assert render_volume(VolumePattern(), None) is None


class TestBlockChar:
    def test_block_char_avoids_label_characters(self):
        p = VolumePattern(label="MAX X#@", min_max_text=True)
        frame = render_volume(p, 50)
        assert frame is not None
        assert frame.block_char not in "MAX X#@"
        assert frame.block_char not in frame.line_one.split("[")[0]

    def test_pick_block_char(self):
        assert pick_block_char("hello") == "X"
        assert pick_block_char("X marks") == "#"


class TestValidation:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("fill_char", "ab"),
            ("fill_char", "|"),
            ("empty_char", "~"),
            ("end_caps", "["),
            ("label", "a" * 31),
            ("label", "Vol|"),
            ("duration", 9),
            ("bar_width", 31),
            ("bar_type", "spiral"),
        ],
    )
    def test_invalid(self, field: str, value: object):
        p = VolumePattern.from_dict({field: value})
        assert field in p.errors()

    def test_round_trip(self):
        p = VolumePattern(label="Sound", lines=2, fill_char="=")
        assert VolumePattern.from_dict(p.to_dict()) == p

    def test_from_dict_coerces_form_values(self):
        p = VolumePattern.from_dict(
            {"lines": "2", "bar_width": 12.0, "duration": 3.0, "unknown": 1}
        )
        assert (p.lines, p.bar_width, p.duration) == (2, 12, 3)

    def test_preview(self):
        text = preview_samples(VolumePattern())
        assert "min:" in text and "muted:" in text
        assert "\u2588" in text
