"""The Slack reconnect banner sits on --bg-elevated (= --surface2); its text must stay WCAG AA."""

import pathlib
import re

STATIC = pathlib.Path(__file__).parent.parent / "static"


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _token(block: str, name: str) -> str:
    return re.search(rf"^\s*--{name}:\s*(#[0-9a-fA-F]{{6}});", block, re.M).group(1)


def test_banner_foreground_meets_aa_in_dark_and_light():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8-sig")
    banner = re.search(r"banner\.id = '_slack_reconnect_banner';.*?cssText =\s*'([^']*)'", js, re.S).group(1)
    fg_token = re.search(r"font-size:0\.85em;color:var\(--([a-z-]+),", banner).group(1)

    dark = css[css.index(":root"):]
    light = css[css.index("[data-theme='light'] {"):]
    for block in (dark, light):
        assert _contrast(_token(block, fg_token), _token(block, "surface2")) >= 4.5
