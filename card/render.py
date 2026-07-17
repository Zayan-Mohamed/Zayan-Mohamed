"""Render the profile card as SVG.

Both themes come from this one template so they cannot drift apart, and every
value on the card is passed in from something that measured it. If a number
here is wrong, the fix belongs upstream in whatever produced it -- there is
nothing on this card that a human types.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

# Measured at 16px against the monospace fallbacks this card actually renders
# in (DejaVu Sans Mono, Liberation Mono and the generic monospace all agree at
# 0.6em). Consolas is narrower at 0.55em, so where it is present the column
# simply ends short of the right margin rather than overflowing it.
CHAR_WIDTH = 9.7
LINE_HEIGHT = 20
TOP = 30
LEFT_X = 15
GUTTER = 24
PAD_BOTTOM = 24

# Width of the right-hand column in characters, used to place the dot leaders.
# Rows longer than this push past the leader minimum and widen the card, so
# values are kept short enough to sit inside it.
COLUMN_CHARS = 64


@dataclass(frozen=True)
class Palette:
    background: str
    text: str
    key: str
    value: str
    dots: str
    accent: str
    add: str
    delete: str


DARK = Palette(
    background="#161b22",
    text="#c9d1d9",
    key="#ffa657",
    value="#a5d6ff",
    dots="#484f58",
    accent="#7ee787",
    add="#3fb950",
    delete="#f85149",
)

LIGHT = Palette(
    background="#ffffff",
    text="#24292f",
    key="#953800",
    value="#0550ae",
    dots="#8c959f",
    accent="#116329",
    add="#1a7f37",
    delete="#cf222e",
)

BANNER = r"""
███████╗ █████╗ ██╗   ██╗ █████╗ ███╗   ██╗
╚══███╔╝██╔══██╗╚██╗ ██╔╝██╔══██╗████╗  ██║
  ███╔╝ ███████║ ╚████╔╝ ███████║██╔██╗ ██║
 ███╔╝  ██╔══██║  ╚██╔╝  ██╔══██║██║╚██╗██║
███████╗██║  ██║   ██║   ██║  ██║██║ ╚████║
╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝
""".strip("\n").split("\n")

# Width of the language bars, in characters.
BAR_CHARS = 22

# How many languages get their own row before the rest collapse into "other".
LANGUAGE_ROWS = 9

# The left column is as wide as the banner; the chart is laid out to match.
ART_CHARS = max(len(line) for line in BANNER)

# Blank rows kept between the left column's content and the wordmark below it.
BANNER_GAP = 2

# The portrait column on the right is rendered at half the card's text size, so
# its 39 rows resolve into an image that sits inside the card's height instead
# of towering over it. Halving both metrics keeps the same character aspect
# ratio as the rest of the card, so the portrait is not stretched.
ART_FONT = 8
ART_CHAR_WIDTH = CHAR_WIDTH / 2
ART_LINE_HEIGHT = LINE_HEIGHT / 2

# xterm 256-colour SGR codes -> RGB. The .ans files colour every glyph with a
# `38;5;N` foreground; background codes are ignored because the card supplies
# its own.
_SGR = re.compile(r"\x1b\[([0-9;]*)m")
_FG256 = re.compile(r"38;5;(\d+)")


def _xterm256(n: int) -> str:
    if n < 16:
        base = [
            (0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0), (0, 0, 128),
            (128, 0, 128), (0, 128, 128), (192, 192, 192), (128, 128, 128),
            (255, 0, 0), (0, 255, 0), (255, 255, 0), (0, 0, 255), (255, 0, 255),
            (0, 255, 255), (255, 255, 255),
        ]
        r, g, b = base[n]
    elif n <= 231:
        n -= 16
        conv = lambda c: 0 if c == 0 else 55 + 40 * c
        r, g, b = conv(n // 36), conv((n % 36) // 6), conv(n % 6)
    else:
        v = 8 + (n - 232) * 10
        r, g, b = v, v, v
    return f"#{r:02x}{g:02x}{b:02x}"


def parse_ans(path) -> list[list[tuple[str, str | None]]]:
    """Parse an ANSI .ans file into rows of (text, colour) runs.

    Colour is the xterm-256 foreground last set by a `38;5;N` code, or None
    when the art never names one -- a monochrome export (foreground left at the
    terminal default) leaves every run None, and the caller paints those in the
    theme's text colour. ANSI state is terminal-global, so the colour persists
    across lines and is reset by a bare `0`. Consecutive same-colour glyphs are
    coalesced. Returns an empty list if the file is missing, so a card can still
    render without a portrait.
    """
    try:
        raw = Path(path).read_text(errors="replace")
    except OSError:
        return []

    rows: list[list[tuple[str, str | None]]] = []
    color: str | None = None
    for line in raw.split("\n"):
        runs: list[tuple[str, str | None]] = []
        i = 0
        for m in _SGR.finditer(line):
            seg = line[i : m.start()]
            if seg:
                if runs and runs[-1][1] == color:
                    runs[-1] = (runs[-1][0] + seg, color)
                else:
                    runs.append((seg, color))
            codes = m.group(1)
            fg = _FG256.search(codes)
            if fg:
                color = _xterm256(int(fg.group(1)))
            elif codes in ("", "0"):
                color = None
            i = m.end()
        seg = line[i:]
        if seg:
            runs.append((seg, color))
        rows.append(runs)

    while rows and not any(text.strip() for text, _ in rows[-1]):
        rows.pop()
    return rows


def _text(s: str) -> str:
    return escape(str(s))


def _wipe(x: int, y: int, w: int, h: int, fill: str, dur: float, hold: float = 0.0) -> str:
    """A background-coloured rectangle that animates out of the way, revealing
    whatever it was covering.

    The reveal is done by *uncovering*, never by drawing, so the honest static
    card is the end state: the rect's base ``width`` is 0, which is what a
    renderer that ignores SMIL (or a viewer who never replays the animation)
    sees -- nothing covered, every measured value already in place. The
    animation only ever starts fully covering and retracts left-to-right.

    ``hold`` (0..1) keeps the cover in place for that fraction of the run before
    it starts retracting, so several wipes sharing one ``begin="0s"`` clock can
    be staggered without any of them flashing their content first.
    """
    x2 = x + w
    ease = "0.4 0 0.2 1"
    if hold <= 0:
        anims = (
            f'<animate attributeName="x" from="{x}" to="{x2}" dur="{dur}s" '
            f'begin="0s" calcMode="spline" keyTimes="0;1" keySplines="{ease}" fill="freeze"/>'
            f'<animate attributeName="width" from="{w}" to="0" dur="{dur}s" '
            f'begin="0s" calcMode="spline" keyTimes="0;1" keySplines="{ease}" fill="freeze"/>'
        )
    else:
        kt = f"0;{hold:.3f};1"
        ks = f"0 0 1 1;{ease}"
        anims = (
            f'<animate attributeName="x" values="{x};{x};{x2}" keyTimes="{kt}" '
            f'dur="{dur}s" begin="0s" calcMode="spline" keySplines="{ks}" fill="freeze"/>'
            f'<animate attributeName="width" values="{w};{w};0" keyTimes="{kt}" '
            f'dur="{dur}s" begin="0s" calcMode="spline" keySplines="{ks}" fill="freeze"/>'
        )
    return f'<rect x="{x}" y="{y}" width="0" height="{h}" fill="{fill}">{anims}</rect>'


def human_bytes(count: int) -> str:
    """Render a byte count the way a terminal would."""
    size = float(count)
    for unit in ("B", "kB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def language_chart(languages: dict[str, int]) -> list[tuple[str, str, str]]:
    """Turn bytes-per-language into rows of (name, bar, percent).

    Anything past the first few languages is summed into a single "other" row
    rather than dropped, so the percentages always total 100 and the chart
    can't quietly misrepresent the tail.
    """
    if not languages:
        return []

    ranked = sorted(languages.items(), key=lambda kv: kv[1], reverse=True)
    total = sum(languages.values())

    head = ranked[:LANGUAGE_ROWS]
    tail = ranked[LANGUAGE_ROWS:]
    if tail:
        head.append(("other", sum(size for _, size in tail)))

    # Bars are scaled against the largest language rather than against 100%.
    # No language here reaches a quarter of the tree, so an absolute scale
    # renders every bar as a stub and the chart stops being readable. The
    # percentage beside each bar carries the absolute share.
    largest = max(size for _, size in head)

    rows = []
    for name, size in head:
        share = size / total
        filled = max(round(size / largest * BAR_CHARS), 1)
        rows.append((name, (filled, BAR_CHARS - filled), f"{share * 100:4.1f}%"))
    return rows


class Column:
    """Accumulates the right-hand column, tracking its own vertical position."""

    def __init__(self, x: int) -> None:
        self.x = x
        self.rows: list[str] = []

    def _y(self) -> int:
        return TOP + len(self.rows) * LINE_HEIGHT

    def blank(self) -> None:
        self.rows.append(f'<tspan x="{self.x}" y="{self._y()}" class="cc">. </tspan>')

    def rule(self, title: str) -> None:
        """A section header padded out with a horizontal rule."""
        dashes = "—" * max(COLUMN_CHARS - len(title) - 4, 2)
        self.rows.append(
            f'<tspan x="{self.x}" y="{self._y()}" class="hd">- {_text(title)} </tspan>'
            f'<tspan class="cc">-{dashes}-—-</tspan>'
        )

    def entry(self, key: str, value: str, ident: str | None = None) -> None:
        """A `key: ....... value` row with dot leaders sized to fit.

        The leader length is computed from the rendered value, so a number that
        grows by a digit stays aligned instead of pushing the column out.
        """
        key_txt, value_txt = str(key), str(value)
        used = 2 + len(key_txt) + 1 + 1 + len(value_txt) + 1
        if used > COLUMN_CHARS:
            # Silently letting this through would push the value off the right
            # edge of the card, where nobody would see it was truncated.
            raise ValueError(
                f"row {key_txt!r} needs {used} chars but the column is "
                f"{COLUMN_CHARS}: shorten the value or widen COLUMN_CHARS"
            )
        dots = "." * max(COLUMN_CHARS - used, 1)

        dots_id = f' id="{ident}_dots"' if ident else ""
        value_id = f' id="{ident}"' if ident else ""

        self.rows.append(
            f'<tspan x="{self.x}" y="{self._y()}" class="cc">. </tspan>'
            f'<tspan class="key">{_text(key_txt)}</tspan>'
            f'<tspan class="cc">:</tspan>'
            f'<tspan class="cc"{dots_id}> {dots} </tspan>'
            f'<tspan class="value"{value_id}>{_text(value_txt)}</tspan>'
        )

    def raw(self, markup: str) -> None:
        self.rows.append(f'<tspan x="{self.x}" y="{self._y()}">{markup}</tspan>')

    def height(self) -> int:
        return TOP + len(self.rows) * LINE_HEIGHT


def render(data: dict, palette: Palette, portrait: list | None = None) -> str:
    """Build the whole SVG for one theme.

    Geometry is derived from the art and the column width rather than hardcoded,
    so changing either cannot silently push text off the edge of the card. A
    ``portrait`` (rows of coloured runs from parse_ans) is placed as a third
    column on the right; passing None omits it and the card is unchanged.
    """
    right_x = LEFT_X + round(ART_CHARS * CHAR_WIDTH) + GUTTER
    info_right = right_x + round(COLUMN_CHARS * CHAR_WIDTH)

    # The portrait column sits to the right of the neofetch info, sized from the
    # widest art row so nothing is clipped.
    portrait = portrait or []
    art_cols = max((sum(len(t) for t, _ in row) for row in portrait), default=0)
    art_x = info_right + GUTTER
    art_w = round(art_cols * ART_CHAR_WIDTH)
    art_h = round(len(portrait) * ART_LINE_HEIGHT)

    if portrait:
        width = art_x + art_w + LEFT_X
    else:
        width = info_right + LEFT_X

    col = Column(right_x)

    # Reveal overlays, drawn on top of the finished card. Each is a
    # background-coloured wipe that retracts to expose a measured value; see
    # _wipe for why this is safe when the animation does not run.
    overlays: list[str] = []

    col.raw(
        f'<tspan class="hd">{_text(data["login"])}</tspan>'
        f'<tspan class="cc"> -{"—" * (COLUMN_CHARS - len(data["login"]) - 4)}-—-</tspan>'
    )
    col.entry("OS", data["os"])
    col.entry("Uptime", data["uptime"], ident="uptime")
    col.entry("Host", data["host"])
    col.entry("Kernel", data["kernel"])
    col.entry("Editor", data["editor"])
    col.blank()

    col.rule("Shipping")
    for repo in data["repos"]:
        col.entry(repo["name"], f"{repo['stars']}★  {repo['summary']}")
    col.blank()

    scan = data["scan"]
    col.rule(f"secscan v{scan['version']}, run against my own code, daily")
    col.entry("Repos scanned", scan["repos"], ident="scan_repos")
    col.entry("Files", f"{scan['files']:,}", ident="scan_files")
    col.entry("Git history", f"{scan['commits']:,} commits", ident="scan_commits")
    col.entry("Scan time", f"{scan['duration_s']:.1f}s", ident="scan_time")
    col.entry(
        "Findings",
        f"{scan['findings']} ({scan['findings_high']} at >=0.9 confidence)",
        ident="scan_findings",
    )
    col.entry("Last run", scan["at"], ident="scan_at")
    col.blank()

    stats = data["stats"]
    col.rule("GitHub")
    col.entry("Repos", f"{stats['repos']}  |  Stars: {stats['stars']}", ident="gh_repos")
    col.entry(
        "Commits",
        f"{stats['commits']:,}  |  Followers: {stats['followers']}",
        ident="gh_commits",
    )

    # The +/- breakdown is coloured, so it is assembled rather than passed
    # through entry().
    loc = f"{stats['loc']:,}"
    label = "Lines of Code on GitHub"
    used = 2 + len(label) + 2 + len(loc) + 1
    tail = f" ( {stats['additions']:,}++, {stats['deletions']:,}-- )"
    dots = "." * max(COLUMN_CHARS - used - len(tail), 1)

    # Geometry for the lines-of-code reveal, captured before the row is placed.
    # The value and its coloured +/- breakdown are the card's headline count, so
    # they get their own wipe that lands just after the language bars settle.
    loc_baseline = TOP + len(col.rows) * LINE_HEIGHT
    add_txt = f"{stats['additions']:,}++"
    del_txt = f"{stats['deletions']:,}--"
    loc_offset = 2 + len(label) + 1 + 1 + len(dots) + 1
    loc_end = loc_offset + len(loc) + len(" ( ") + len(add_txt) + len(", ") + len(del_txt) + len(" )")
    loc_x = col.x + round(loc_offset * CHAR_WIDTH)
    loc_w = round((loc_end - loc_offset) * CHAR_WIDTH)
    overlays.append(
        _wipe(loc_x, loc_baseline - 15, loc_w, 20, palette.background, dur=1.9, hold=0.55)
    )

    col.rows.append(
        f'<tspan x="{col.x}" y="{col._y()}" class="cc">. </tspan>'
        f'<tspan class="key">{label}</tspan>'
        f'<tspan class="cc">:</tspan>'
        f'<tspan class="cc" id="loc_dots"> {dots} </tspan>'
        f'<tspan class="value" id="loc">{loc}</tspan>'
        f'<tspan class="cc"> ( </tspan>'
        f'<tspan class="add" id="loc_add">{stats["additions"]:,}++</tspan>'
        f'<tspan class="cc">, </tspan>'
        f'<tspan class="del" id="loc_del">{stats["deletions"]:,}--</tspan>'
        f'<tspan class="cc"> )</tspan>'
    )

    # Left column: the language chart and contact, with the wordmark anchored to
    # the bottom of the card. Everything here is measured -- the one piece of
    # deliberate art on the card is the portrait in the right column, and it is
    # a self-portrait rather than a mascot: it says "this is me", not "here is a
    # cute thing".
    left: list[str] = []

    def left_row(markup: str) -> None:
        left.append(f'<tspan x="{LEFT_X}" y="{TOP + len(left) * LINE_HEIGHT}">{markup}</tspan>')

    rule = "—" * max(ART_CHARS - len("- Source by language ") - 3, 2)
    left_row(f'<tspan class="hd">- Source by language </tspan><tspan class="cc">-{rule}-—-</tspan>')

    name_width = max((len(name) for name, _, _ in data["languages"]), default=0)
    pct_width = max((len(p) for _, _, p in data["languages"]), default=0)

    # The bars are the measured centrepiece, so they get the leading reveal: a
    # single wipe across the whole bar+percent block. Because it uncovers
    # left-to-right and the bars differ in length, short bars finish early while
    # long ones keep extending -- the wipe reads as each bar growing to its true
    # proportion. Names stay put as static labels.
    if data["languages"]:
        first_bar_row = len(left)
        n_bars = len(data["languages"])
        bar_x = LEFT_X + round((name_width + 1) * CHAR_WIDTH)
        bar_w = round((BAR_CHARS + 1 + pct_width) * CHAR_WIDTH)
        bar_y = TOP + first_bar_row * LINE_HEIGHT
        overlays.append(
            _wipe(
                bar_x,
                bar_y - 15,
                bar_w,
                (n_bars - 1) * LINE_HEIGHT + 20,
                palette.background,
                dur=1.5,
            )
        )

    for name, (filled, empty), percent in data["languages"]:
        left_row(
            f'<tspan class="key">{_text(name.ljust(name_width))}</tspan>'
            f'<tspan class="cc"> </tspan>'
            f'<tspan class="bar">{"█" * filled}</tspan>'
            f'<tspan class="cc">{"░" * empty}</tspan>'
            f'<tspan class="cc"> </tspan>'
            f'<tspan class="value">{_text(percent)}</tspan>'
        )

    left_row("")
    left_row(
        f'<tspan class="cc">measured across {data["stats"]["repos"]} repos · </tspan>'
        f'<tspan class="value">{_text(data["language_total"])}</tspan>'
        f'<tspan class="cc"> of source</tspan>'
    )

    # Contact lives under the chart rather than in the right column: it is short
    # enough to fit the narrower side, and putting it here keeps the two columns
    # roughly the same height instead of leaving the left one half empty.
    left_row("")
    rule = "—" * max(ART_CHARS - len("- Contact ") - 3, 2)
    left_row(f'<tspan class="hd">- Contact </tspan><tspan class="cc">-{rule}-—-</tspan>')

    contact_width = max(len(key) for key, _ in data["contact"])
    for key, value in data["contact"]:
        left_row(
            f'<tspan class="key">{_text(key.ljust(contact_width))}</tspan>'
            f'<tspan class="cc">  </tspan>'
            f'<tspan class="value">{_text(value)}</tspan>'
        )

    # The wordmark sits on the bottom edge, so the height has to account for it
    # plus a gap before it can be placed.
    banner_rows = len(BANNER)
    left_needed = len(left) + BANNER_GAP + banner_rows
    height = max(col.height(), TOP + left_needed * LINE_HEIGHT) + PAD_BOTTOM
    # The portrait is shorter than the card today, but guard against a taller
    # one pushing past the floor rather than clipping it silently.
    height = max(height, art_h + 2 * PAD_BOTTOM)

    # Anchor the wordmark to the bottom rather than to the end of the content,
    # so it lands on the card's floor whichever column happens to be taller.
    banner_top = height - PAD_BOTTOM - (banner_rows - 1) * LINE_HEIGHT
    left.extend(
        f'<tspan x="{LEFT_X}" y="{banner_top + i * LINE_HEIGHT}">{_text(line)}</tspan>'
        for i, line in enumerate(BANNER)
    )

    art = "\n".join(left)

    # The portrait, centred vertically in the finished card. Each row is one
    # <text> at the half-size font; runs within a row flow by the monospace
    # advance, so nothing needs per-glyph positioning.
    portrait_lines = []
    if portrait:
        art_top = round((height - art_h) / 2)
        for i, row in enumerate(portrait):
            if not any(text.strip() for text, _ in row):
                continue
            baseline = art_top + round(i * ART_LINE_HEIGHT) + ART_FONT
            runs = "".join(
                f'<tspan fill="{color or palette.text}">{_text(text)}</tspan>'
                for text, color in row
            )
            portrait_lines.append(
                f'<text x="{art_x}" y="{baseline}" font-size="{ART_FONT}px">{runs}</text>'
            )
    portrait_svg = "\n".join(portrait_lines)

    return f"""<?xml version='1.0' encoding='UTF-8'?>
<svg xmlns="http://www.w3.org/2000/svg" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,'DejaVu Sans Mono','Liberation Mono',monospace" width="{width}px" height="{height}px" font-size="16px">
<style>
.key {{ fill: {palette.key}; }}
.value {{ fill: {palette.value}; }}
.cc {{ fill: {palette.dots}; }}
.bar {{ fill: {palette.accent}; }}
.hd {{ fill: {palette.accent}; font-weight: bold; }}
.add {{ fill: {palette.add}; }}
.del {{ fill: {palette.delete}; }}
text, tspan {{ white-space: pre; }}
</style>
<rect width="{width}px" height="{height}px" fill="{palette.background}" rx="15"/>
<text x="{LEFT_X}" y="{TOP}" fill="{palette.text}" class="ascii">
{art}
</text>
<text x="{right_x}" y="{TOP}" fill="{palette.text}">
{chr(10).join(col.rows)}
</text>
{portrait_svg}
{chr(10).join(overlays)}
</svg>
"""
