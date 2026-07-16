"""Render the profile card as SVG.

Both themes come from this one template so they cannot drift apart, and every
value on the card is passed in from something that measured it. If a number
here is wrong, the fix belongs upstream in whatever produced it -- there is
nothing on this card that a human types.
"""

from __future__ import annotations

from dataclasses import dataclass
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


def _text(s: str) -> str:
    return escape(str(s))


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


def render(data: dict, palette: Palette) -> str:
    """Build the whole SVG for one theme.

    Geometry is derived from the art and the column width rather than hardcoded,
    so changing either cannot silently push text off the edge of the card.
    """
    right_x = LEFT_X + round(ART_CHARS * CHAR_WIDTH) + GUTTER
    width = right_x + round(COLUMN_CHARS * CHAR_WIDTH) + LEFT_X

    col = Column(right_x)

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
    # the bottom of the card. There is no decorative art here on purpose --
    # everything on this card is measured, and a mascot would have been the only
    # thing on it that wasn't.
    left: list[str] = []

    def left_row(markup: str) -> None:
        left.append(f'<tspan x="{LEFT_X}" y="{TOP + len(left) * LINE_HEIGHT}">{markup}</tspan>')

    rule = "—" * max(ART_CHARS - len("- Source by language ") - 3, 2)
    left_row(f'<tspan class="hd">- Source by language </tspan><tspan class="cc">-{rule}-—-</tspan>')

    name_width = max((len(name) for name, _, _ in data["languages"]), default=0)
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

    # Anchor the wordmark to the bottom rather than to the end of the content,
    # so it lands on the card's floor whichever column happens to be taller.
    banner_top = height - PAD_BOTTOM - (banner_rows - 1) * LINE_HEIGHT
    left.extend(
        f'<tspan x="{LEFT_X}" y="{banner_top + i * LINE_HEIGHT}">{_text(line)}</tspan>'
        for i, line in enumerate(BANNER)
    )

    art = "\n".join(left)

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
</svg>
"""
