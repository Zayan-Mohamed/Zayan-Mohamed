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

TUX = r"""
                 .88888888:.
                88888888.88888.
              .8888888888888888.
              888888888888888888
              88' _`88'_  `88888
              88 88 88 88  88888
              88_88_::_88_:88888
              88:::,::,:::::8888
              88`:::::::::'`8888
             .88  `::::'    8:88.
            8888            `8:888.
          .8888'             `888888.
         .8888:..  .::.  ...:'8888888:.
        .8888.'     :'     `'::`88:88888
       .8888        '         `.888:8888.
      888:8         .           888:88888
    .888:88        .:           888:88888:
    8888888.       ::           88:888888
    `.::.888.      ::          .88888888
   .::::::.888.    ::         :::`8888'.:.
  ::::::::::.888.  :       .:8888.::::::::
  ::::::::::::.8888.     ..:8888888:.:::::
  ::::::::::::::88888...::88888888::::::::
  ::::::::::::::::88888:88888888888::::::
""".strip("\n").split("\n")


def _text(s: str) -> str:
    return escape(str(s))


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
    art_rows = BANNER + ["", ""] + TUX
    art_chars = max(len(line) for line in art_rows)
    right_x = LEFT_X + round(art_chars * CHAR_WIDTH) + GUTTER
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
    col.entry("Languages.Programming", data["languages"])
    col.entry("Languages.Computer", data["markup"])
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
    col.blank()

    col.rule("Contact")
    for key, value in data["contact"]:
        col.entry(key, value)

    art = "\n".join(
        f'<tspan x="{LEFT_X}" y="{TOP + i * LINE_HEIGHT}">{_text(line)}</tspan>'
        for i, line in enumerate(art_rows)
    )

    height = max(col.height(), TOP + len(art_rows) * LINE_HEIGHT) + PAD_BOTTOM

    return f"""<?xml version='1.0' encoding='UTF-8'?>
<svg xmlns="http://www.w3.org/2000/svg" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,'DejaVu Sans Mono','Liberation Mono',monospace" width="{width}px" height="{height}px" font-size="16px">
<style>
.key {{ fill: {palette.key}; }}
.value {{ fill: {palette.value}; }}
.cc {{ fill: {palette.dots}; }}
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
