"""The modern look's colour palette, for code that must paint colours itself.

Widgets should get their colours from the theme QSS (app/resources/themes/
*.qss, "Modern widget kit" section) via object names and `state`/`kind`
properties. Some things can't be styled by QSS — syntax highlighters, HTML
rendered into a QTextBrowser, pyqtgraph plots, custom paintEvents — and those
read colours from here instead of hard-coding hex values.

The values mirror the QSS exactly. Keep the palette minimal: reuse a token
rather than adding a new colour, and if a value changes, change it in both
QSS files too.
"""
from __future__ import annotations

PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "page":        "#1e1e1e",   # window background behind cards
        "card":        "#252526",   # card surface
        "field":       "#2d2d2d",   # inputs, keys, raised surfaces inside cards
        "row":         "#2b2b2c",   # list rows / file rows inside cards
        "border":      "#333333",   # card border
        "border2":     "#3a3a3a",   # input / button border
        "text":        "#d4d4d4",   # body text
        "strong":      "#e6e6e6",   # titles, emphasised values
        "muted":       "#8a8a8a",   # secondary text, captions
        "accent":      "#4ea1f3",   # primary action, selection, links, progress
        "accent_soft": "#1e3a5f",   # selected / checked background
        "ok":          "#22c55e",   # success, online, live
        "warn":        "#f59e0b",   # caution
        "err":         "#ef4444",   # failure, danger, recording
        "console_bg":  "#1a1a1a",   # code / console surface
        "console_fg":  "#c8c8c8",   # code / console text
        "sel":         "#264f78",   # text selection
    },
    "light": {
        "page":        "#f5f5f5",
        "card":        "#ffffff",
        "field":       "#ffffff",
        "row":         "#f8f9fb",
        "border":      "#e3e3e3",
        "border2":     "#d0d0d0",
        "text":        "#1a1a1a",
        "strong":      "#111827",
        "muted":       "#6b7280",
        "accent":      "#1a56db",
        "accent_soft": "#e3eaf7",
        "ok":          "#16a34a",
        "warn":        "#b45309",
        "err":         "#dc2626",
        "console_bg":  "#fafafa",
        "console_fg":  "#1f2937",
        "sel":         "#cfe0fb",
    },
}


def palette(theme: str | None = None) -> dict[str, str]:
    """All tokens for `theme` (default: the active theme)."""
    if theme is None:
        from app.core.theme_manager import theme_manager
        theme = theme_manager.current
    return PALETTES.get(theme, PALETTES["dark"])


def color(token: str, theme: str | None = None) -> str:
    """One token's hex value for `theme` (default: the active theme)."""
    return palette(theme)[token]
