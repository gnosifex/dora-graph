#!/usr/bin/env python3
"""Verify docs/index.html against data/graph.json — file-based, no browser, no server.

Five families of checks:
  * the page:   placeholder replaced, script tags paired, JS structurally intact and
                still carrying the render decisions the design depends on, the opening
                sequence wired the way the design requires, the narrow-screen layout
                present and fed by measured panels, and the whole document
                self-contained — no address but the repo link, nothing fetched
  * the payload the page embeds: field names, index ranges, date shapes, and agreement
                with data/graph.json on counts, titles and supersession edges
  * the geometry, for BOTH layouts (final picture and pre-impact pack): zero overlaps in
                every pair category, containment, uniform unit radii, the free-node cap,
                label collisions, connectivity, and the 1,5 x DORA distance guard rail
  * the two still images, docs/preview.svg and docs/social-card.svg: well-formed XML,
                one circle per graph node, nothing that a host would strip or refuse to
                fetch, and a readability pass — nothing outside the frame, no label
                sitting on a circle, enough contrast against the painted ground. The
                preview carries no chrome at all, since the README frames it; the card
                stands alone when it is shared, so it keeps its title and colour key
                and additionally holds GitHub's 40 pt guard

Exits non-zero as soon as one check fails.
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# has to stay in step with build_site's label model
LABEL_FS, LABEL_CHAR_W = 11.0, 0.60

# has to stay in step with build_site's SVG text metric — the file cannot measure a
# string, so writer and reader share one table of advance widths
SVG_NS = "http://www.w3.org/2000/svg"
SVG_WIDE = set("mwMW—…%@")
SVG_NARROW = set(" iljtfrI.,:;'’!|()[]{}-–/·")


def text_width(text: str, fs: float) -> float:
    u = 0.0
    for c in text:
        if c in SVG_WIDE:
            u += 0.92
        elif c in SVG_NARROW:
            u += 0.34
        elif c.isupper() or c.isdigit():
            u += 0.64
        else:
            u += 0.54
    return u * fs


def boxes_overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def box_inside(a, outer) -> bool:
    return (a[0] >= outer[0] - 0.5 and a[1] >= outer[1] - 0.5
            and a[2] <= outer[2] + 0.5 and a[3] <= outer[3] + 0.5)


def box_hits_circle(box, circle) -> bool:
    cx, cy, r = circle
    nx = min(max(cx, box[0]), box[2])
    ny = min(max(cy, box[1]), box[3])
    return math.hypot(cx - nx, cy - ny) < r


def blend(fg: str, bg: str, alpha: float) -> str:
    """What the eye actually gets when a fill is drawn at less than full opacity."""
    out = [round(int(fg[i:i + 2], 16) * alpha + int(bg[i:i + 2], 16) * (1 - alpha))
           for i in (1, 3, 5)]
    return "#" + "".join(f"{v:02x}" for v in out)


def relative_luminance(colour: str) -> float:
    def channel(v: int) -> float:
        f = v / 255.0
        return f / 12.92 if f <= 0.04045 else ((f + 0.055) / 1.055) ** 2.4
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    a, b = relative_luminance(fg), relative_luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


FAIL: list[str] = []


def ok(cond: bool, label: str, detail: str = "") -> None:
    print(("  OK   " if cond else "  FAIL ") + label + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAIL.append(label)


def check_file(html: str) -> None:
    print("== file")
    ok("__DATA__" not in html, "placeholder __DATA__ replaced")
    ok(html.count("<script") == html.count("</script>"), "script tags paired")
    ok(html.rstrip().endswith("</html>"), "document complete")


def check_js(html: str) -> str:
    print("\n== JS block (structural)")
    js = re.search(r"<script>\n(.*?)\n</script>", html, re.S).group(1)
    ok("</script>" not in js, "no unescaped </script> inside the JS")

    # strip strings and comments, then balance the brackets (this code has no regex
    # literals, which the next check asserts rather than assumes)
    ok(not re.search(r"[=(,:]\s*/[^/*\s]", js), "no regex literals (scanner assumption)")
    clean: list[str] = []
    i, n, state = 0, len(js), None
    while i < n:
        c = js[i]
        if state is None:
            if c in "\"'`":
                state = c
            elif c == "/" and i + 1 < n and js[i + 1] == "/":
                state = "//"
                i += 1
            elif c == "/" and i + 1 < n and js[i + 1] == "*":
                state = "/*"
                i += 1
            else:
                clean.append(c)
        elif state in "\"'`":
            if c == "\\":
                i += 1
            elif c == state:
                state = None
        elif state == "//":
            if c == "\n":
                state = None
        elif state == "/*":
            if c == "*" and i + 1 < n and js[i + 1] == "/":
                state = None
                i += 1
        i += 1
    ok(state is None, "strings/comments closed", f"open: {state}")
    text = "".join(clean)
    for open_c, close_c in (("{", "}"), ("(", ")"), ("[", "]")):
        depth = mn = 0
        for c in text:
            if c == open_c:
                depth += 1
            elif c == close_c:
                depth -= 1
                mn = min(mn, depth)
        ok(depth == 0 and mn == 0, f"brackets {open_c}{close_c} balanced", f"rest {depth}, min {mn}")
    for name in ("function step", "function draw", "function frame", "function resize",
                 "function buildTicks", "function place", "function impactEase",
                 "function impactRaw", "function gA", "JSON.parse",
                 "requestAnimationFrame(frame)"):
        ok(name in js, f"present: {name}")
    ok(js.index("var supers = []") < js.index("// 2) act containers"),
       "z-order: edges drawn before the circles")
    ok(js.index("// 4) point nodes") < js.index("// 5) act labels"),
       "z-order: labels drawn last")
    ok('li.addEventListener("click"' in js and "sel = (sel === key) ? null : key" in js,
       "legend: a rank row toggles the highlight")
    ok('fold.addEventListener("click"' in js, "legend: collapsible")
    ok('nf.addEventListener("click"' in js and "setNote(stored(NKEY)" in js,
       "legend: the reading notes are their own fold, restored from storage")
    ok("setLineDash(full ? [6 * scale, 4 * scale] : [2.5 * scale, 5 * scale])" in js,
       "supersession edges still red dashed/dotted")
    ok("if (n.partial) ctx.setLineDash([4.5 * scale, 3.5 * scale])" in js,
       "estimate rings still dashed")
    ok('SPAN = { prop: 45, compact: 30 }' in js, "proportional 45 s / compact 30 s")
    ok("nodes[IMP.k].born" in js and "IMP.reach" in js, "impact ring pulse present")
    check_endstate(js)
    return js


def check_endstate(js: str) -> None:
    """The last frame has to be the still image.

    Two things have to hold, and they are checked separately because they fail
    separately: the clock has to run on past the last appearance long enough for the
    fade and the settling spring to finish, and the end has to be set as a state so
    that jumping straight to it cannot show a half-finished frame.
    """
    print("\n== timeline: the end is the still image")

    def num(name: str) -> float | None:
        m = re.search(rf"\b{name} = (-?[0-9.]+)", js)
        return float(m.group(1)) if m else None

    fade, spring, keep = num("FADE"), num("SPRING"), num("KEEP")
    born_max, born_min = num("BORN_MAX"), num("BORN_MIN")
    spans = re.search(r"SPAN = \{ prop: ([0-9.]+), compact: ([0-9.]+) \}", js)
    ok(None not in (fade, spring, keep, born_max, born_min) and spans is not None,
       "the run-out is built from named constants, not a magic number")
    if None in (fade, spring, keep, born_max, born_min) or spans is None:
        return

    # the same arithmetic the page does, redone here: an over-damped spring
    # x'' + DECAY x' + SPRING x = 0 leaves the slow root as the one that decides
    decay = -math.log(keep)
    ok(decay * decay - 4 * spring > 0, "the settling spring is over-damped, so it "
       "cannot ring", f"decay {decay:.3f} vs 2*sqrt(pull) {2 * math.sqrt(spring):.3f}")
    rate = (decay - math.sqrt(max(decay * decay - 4 * spring, 0))) / 2
    settle = math.log(born_max / 0.1) / rate
    tail = fade + settle
    ok(re.search(r"TAIL = FADE \+ Math\.log\(BORN_MAX / 0\.1\) / RATE", js) is not None,
       "the page derives the run-out rather than guessing it", f"{tail:.2f} s")
    ok(tail >= fade + 2.0, "the run-out covers the fade and the settling",
       f"fade {fade:g} s + settle {settle:.2f} s = {tail:.2f} s")
    # The formula solves for a residue of a tenth of a design unit, so restating that is
    # no test. What is worth asserting is that the target is small against the thing it
    # is a residue of — the smallest offset a node is ever born with.
    ok(0.1 <= 0.05 * born_min, "the run-out aims well past the point where a node's "
       "birth offset could still be seen",
       f"0.1 units left of a {born_min:g}-{born_max:g} unit offset")
    for name, sp in (("proportional", float(spans.group(1))),
                     ("compact", float(spans.group(2)))):
        # the last node appears at exactly the span, so it is the one with least time
        ok(sp + tail - (sp + fade) >= 0 and sp + tail - (sp + settle) >= 0,
           f"{name}: the last-born node finishes inside the timeline",
           f"appears at {sp:g} s, needs {max(fade, settle):.2f} s, has {tail:.2f} s")

    ok("function duration() { return span() + TAIL; }" in js,
       "the played span is the appearances plus the run-out")
    ok("function appearT(n) { return (mode === \"prop\" ? n.ap : n.ac) * span(); }" in js,
       "the run-out does not stretch the appearance times")

    print("\n== timeline: the date stops at the last document")
    ok("function shown() { return Math.min(tNow / span(), 1); }" in js,
       "there is a separate reading for how far the corpus has come")
    dv = js.split("function currentDV", 1)[-1].split("}", 2)[0]
    ok("shown()" in dv and "progress()" not in dv,
       "the readout follows the corpus, not the animation clock")
    ok("barFor(f)" in js.split("function buildTicks", 1)[-1],
       "the year ticks sit on the bar the run-out lengthened")

    print("\n== timeline: the end state is set, not settled into")
    body = js.split("function settleAll", 1)[-1].split("function step", 1)[0]
    for frag, label in (("n.born = true; n.a = 1;", "every node fully opaque"),
                        ("n.x = n.sx; n.y = n.sy;", "every node on its solved seat"),
                        ("n.vx = 0; n.vy = 0;", "nothing left moving")):
        ok(frag in body, f"at the end: {label}")
    ok("for (var q = 0; q < nodes.length; q++)" in body,
       "the end state covers every node, not just the visible ones")
    ok("if (tNow >= duration()) return settleAll();" in js,
       "reaching the end by any route gives that state in the same frame")
    # and backwards out of it again
    tail_free = js.split("if (tNow >= duration()) return settleAll();", 1)[-1]
    ok("} else { n.born = false; n.a = 0; }" in tail_free,
       "scrubbing back before a node's date un-births it again")


# The only address the page may carry. Everything else it needs it draws or generates
# itself, so the document works offline and asks nobody anything.
REPO_URL = "https://github.com/gnosifex/dora-graph"


def check_opening(html: str, js: str) -> None:
    print("\n== opening sequence")
    for frag in ('id="intro"', 'id="crawlwrap"', 'id="crawl"', 'id="stars"',
                 'id="skip"', 'id="intro-again"'):
        ok(frag in html, f"markup present: {frag}")
    ok("perspective:" in html and "rotateX(" in html, "text plane runs back in perspective")
    # one flat line, so a sentence the source wraps is still one string to look for
    body = " ".join(html.split('id="crawl"', 1)[-1].split("</div>", 1)[0].split())
    # The last two are substance, not decoration: the timeline opens in 2006 with the
    # European banking layer, so the stock the opening names has to include it; and the
    # whole selection is made from one vantage point, which the reader is owed up front
    # rather than in the README.
    for line in ("Ein Blick auf die digitale operationale Resilienz",
                 "Die Geburt einer Regulatorik-Galaxie",
                 "Keine Rechtsberatung.",
                 "die europäischen Banken-Richtlinien",
                 "Perspektive eines deutschen Kreditinstituts"):
        ok(line in body, f"crawl carries: {line[:44]}")
    for name in ("function startIntro", "function finishIntro", "function introStep",
                 "function introLayout", "function drawStars", "function seeded"):
        ok(name in js, f"present: {name}")
    ok('skipBtn.addEventListener("click"' in js, "skip: the button")
    ok('intro.addEventListener("click"' in js, "skip: a click anywhere on the overlay")
    ok('ev.key === "Escape"' in js, "skip: Esc")
    ok('introActive && (ev.code === "Space"' in js, "skip: space bar")
    ok("if (introActive) introStep(" in js, "the opening runs on the render clock")
    dur = re.search(r"INTRO_DUR = (\d+)", js)
    ok(bool(dur) and 30 <= int(dur.group(1)) <= 40, "opening runs 30-40 s",
       dur.group(1) + " s" if dur else "not found")
    ok("finishIntro();" in js and 'store(IKEY, "1")' in js, "seen state written to localStorage")
    ok('stored(IKEY) === "1"' in js, "a returning visitor skips the opening")
    ok('introBtn.addEventListener("click", function () { startIntro(); })' in js,
       "the bar can replay the opening")
    ok("prefers-reduced-motion" in js and "reduce) {" in js, "reduced motion honoured")
    ok("Math.random()" not in js.split("function drawStars", 1)[-1].split("function introLayout", 1)[0],
       "star field is seeded, not random")


def prose(fragment: str) -> str:
    """The running text a reader actually faces: markup, the rank rows the legend is
    built from, and their counts are not prose and are not counted as such. Entities
    are resolved, because a reader sees the character, not the escape."""
    txt = html_mod.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return " ".join(txt.split())


def check_head(html: str) -> None:
    """The head panel names the picture and carries the way back to the sources.

    The link sits on the counts line, where no fold can reach it and the bar does not
    have to spend a control on it.
    """
    print("\n== head panel")
    head = html.split('id="head"', 1)[-1].split('</div>\n\n<div class="panel"', 1)[0]
    ok('id="repo"' in head and REPO_URL in head,
       "the repo link sits in the head panel, clear of every fold")
    anchor = head.split('id="repo"', 1)[-1][:260]
    ok('target="_blank"' in anchor and 'rel="noopener"' in anchor,
       "the repo link opens safely in a new tab")
    ok("github.com/gnosifex/dora-graph</a>" in anchor,
       "the link reads as the address it goes to")
    ok('id="meta"' in head and head.index('id="counts"') < head.index('id="repo"'),
       "the link shares the counts line rather than a line of its own")
    ok("#repo:hover" in html and "text-decoration: underline" in html,
       "the link underlines on hover only")
    bar = html.split('id="bar"', 1)[-1]
    ok('id="repo"' not in bar, "the bar no longer carries a repo button")


# The symbol rows, in the order the panel has to run them: areas, then points, then
# lines. Each row is a glyph class and the caption that names what that stroke is.
LEGEND_ROWS = [
    ("ring", "Rechtsakt; die Punkte darin seine Artikel"),
    ("est", "non-DORA: nur Ausschnitt im Korpus, Umfang geschätzt"),
    ("dot", "eigenständiges Dokument (Leitlinie, Report, Q&A, Aufsichtsseite)"),
    ("ref", "Verweis/Bezug"),
    ("sup-full", "von DORA vollständig verdrängt"),
    ("sup-part", "teilweise verdrängt"),
]

# Glyph geometry the stylesheet fixes and the canvas has no say in: how many whole dash
# cycles are laid around each of the two rings, so the pattern closes instead of showing
# a seam. Everything else about the glyphs is derived from the canvas parameters.
GLYPH_RING_CYCLE, GLYPH_DOT_CYCLE = 90.0, 120.0


def css_rule(sheet: str, selector: str) -> str:
    """One declaration block, whitespace normalised, so a wrapped rule reads as one line."""
    m = re.search(re.escape(selector) + r"(?![-\w])\s*\{(.*?)\}", sheet, re.S)
    return " ".join(m.group(1).split()) if m else ""


def css_alpha(a: float) -> str:
    return f"{a:g}".lstrip("0") or "0"


def canvas_strokes(js: str) -> dict:
    """What the renderer actually draws, read out of the script.

    The legend claims to show the picture's own strokes, so the glyph patterns are
    checked against these numbers rather than against themselves.
    """
    out: dict = {}
    m = re.search(r"setLineDash\(full \? \[([\d.]+) \* scale, ([\d.]+) \* scale\] : "
                  r"\[([\d.]+) \* scale, ([\d.]+) \* scale\]\)", js)
    if m:
        out["sup_full"] = (float(m.group(1)), float(m.group(2)))
        out["sup_part"] = (float(m.group(3)), float(m.group(4)))
    m = re.search(r'"rgba\((\d+,\d+,\d+)," \+ \(S\[2\] \* \(full \? ([\d.]+) : ([\d.]+)\)\)', js)
    if m:
        out["sup_colour"] = m.group(1)
        out["sup_alpha"] = (float(m.group(2)), float(m.group(3)))
    m = re.search(r'"rgba\((\d+,\d+,\d+)," \+ \(al \* [\d.]+\)', js)
    if m:
        out["ref_colour"] = m.group(1)
    m = re.search(r"if \(n\.partial\) ctx\.setLineDash\(\[([\d.]+) \* scale, "
                  r"([\d.]+) \* scale\]\)", js)
    if m:
        out["ring_est"] = (float(m.group(1)), float(m.group(2)))
    m = re.search(r"setLineDash\(\[([\d.]+) \* scale, ([\d.]+) \* scale\]\)",
                  js.split("// 4) point nodes", 1)[-1])
    if m:
        out["dot_est"] = (float(m.group(1)), float(m.group(2)))
    return out


def check_glyphs(html: str, js: str) -> None:
    """Every glyph in the legend repeats the stroke the canvas draws for that element.

    The point is that nothing has to be translated: what the reader sees in the panel is
    the same pattern, at the same ratio, as the thing it names in the picture. So the
    dash arrays and colours are lifted out of the renderer and then looked for in the
    stylesheet — a glyph that drifts away from the canvas fails here.
    """
    print("\n== legend glyphs repeat the canvas strokes")
    s = canvas_strokes(js)
    ok(len(s) == 7, "the canvas stroke parameters are all readable", ", ".join(sorted(s)))
    if len(s) != 7:
        return

    lines = [(".sup-full", *s["sup_full"], s["sup_colour"], s["sup_alpha"][0], "6/4 dashed"),
             (".sup-part", *s["sup_part"], s["sup_colour"], s["sup_alpha"][1], "2.5/5 dotted")]
    for sel, on, off, col, alpha, what in lines:
        rule = css_rule(html, "#legend " + sel + "::before")
        want = (f"rgba({col},{css_alpha(alpha)}) 0 {on:g}px, "
                f"rgba({col},0) {on:g}px {on + off:g}px")
        ok(want in rule, f"{sel}: the supersession glyph is the canvas' {what} line", want)

    rule = css_rule(html, "#legend .ref::before")
    ok(f"rgba({s['ref_colour']}," in rule and "height: 1px" in rule,
       ".ref: the reference glyph is the canvas' 1 px line in its own colour",
       s["ref_colour"])

    rings = [(".est::before", *s["ring_est"], GLYPH_RING_CYCLE, "act ring"),
             (".est::after", *s["dot_est"], GLYPH_DOT_CYCLE, "dot ring")]
    for sel, on, off, cycle, what in rings:
        rule = css_rule(html, "#legend " + sel)
        span = round(on / (on + off) * cycle, 1)
        want = f"0 {span:g}deg, rgba(143,155,176,0) {span:g}deg {cycle:g}deg"
        ok(want in rule, f"{sel}: the estimate glyph carries the {what}'s "
           f"{on:g}/{off:g} dash", want)
    ok(css_rule(html, "#legend .ring::before").count("solid") == 1,
       ".ring: the act ring is drawn solid, as the canvas draws it")


def check_legend(html: str, js: str) -> None:
    """The legend decodes the picture; it does not explain it.

    Everything the opening already says was moved out of here, so the panel stays short
    enough to read at a glance, and the caveat that must never be hidden sits outside
    both folds.
    """
    print("\n== legend")
    panel = html.split('id="legend">', 1)[-1].split("</div>\n\n<div class=\"panel\"", 1)[0]
    note = re.search(r'<div class="note" id="note" hidden>(.*?)</div>', panel, re.S)
    ok(note is not None, "the reading notes are a section of their own")
    if note is None:
        return
    folded = prose(note.group(1))
    # the panel heading and the fold's own label are controls, not prose — they name
    # what is there, they do not explain the picture
    rest = panel.replace(note.group(0), " ")
    rest = re.sub(r"<h2>.*?</h2>", " ", rest, flags=re.S)
    rest = re.sub(r'<button id="notefold".*?</button>', " ", rest, flags=re.S)
    visible = prose(rest)
    # 280, not the 220 of the older panel: the shapes the picture is built from are six,
    # not three — the plain grey line is 587 of its 590 edges and cannot go unnamed —
    # and a shape that is drawn has to be named where it is seen, not in the fold.
    ok(len(visible) < 280, "the legend a reader faces stays under 280 characters",
       f"{len(visible)} chars: {visible[:70]}…")

    key = re.search(r'<div class="key">(.*?)\n  </div>', panel, re.S)
    ok(key is not None, "the symbol rows are a block of their own")
    if key is not None:
        rows = re.findall(r'<span class="g ([\w-]+)"></span>([^<]*)</div>', key.group(1))
        rows = [(cls, html_mod.unescape(text).strip()) for cls, text in rows]
        ok(rows == LEGEND_ROWS, "six symbol rows, areas then points then lines",
           f"{len(rows)} rows: " + ", ".join(c for c, _ in rows))
    ok("Warm" not in visible and "kühl" not in visible,
       "no warm/cool line: the nine labelled rank rows above it say the same thing")
    ok(len(folded) < 380, "the folded notes stay under 380 characters",
       f"{len(folded)} chars")
    ok('id="note" hidden' in panel and 'aria-expanded="false"' in panel,
       "the notes are shut when the page loads")
    ok("Keine Rechtsberatung." in visible,
       "the caveat is outside the fold, where it cannot be hidden")
    ok('class="caveat"' in panel and panel.index('id="note"') < panel.index('class="caveat"'),
       "the caveat stands after the fold, not inside it")
    ok("Klick auf eine Zeile" in panel and "Klick auf eine Zeile" not in visible,
       "the click hint is a tooltip on the list, not another line of prose")
    ok('id="repo"' not in panel, "the repo link is not inside the legend")
    ok("max-height: calc(100vh" in html and "overflow-y: auto" in html,
       "a low window scrolls the legend instead of cutting it off")


def check_mobile(html: str, js: str) -> None:
    """The narrow-screen layout, as far as a file can be read without a browser.

    Nothing here renders, so the pass asserts the mechanism rather than the picture:
    the breakpoint exists and the stylesheet and the script agree on it, the panels
    give up their floating boxes for the screen edges, the bar wraps and keeps
    finger-sized targets, the legend becomes a folded overlay, and — the one that
    decides whether anything is visible at all — the fit measures the panels instead
    of assuming a desktop column.
    """
    print("\n== narrow screens")
    ok('name="viewport"' in html and "width=device-width" in html, "viewport meta present")
    query = re.search(r"@media \(max-width: 720px\) \{(.*?)\n  /\*", html, re.S)
    ok(query is not None, "there is a phone breakpoint at 720 px")
    if query is None:
        return
    mq = query.group(1)
    ok("var MOBILE_W = 720" in js, "the script uses the same breakpoint as the stylesheet")

    for frag, label in (("#head {", "head plate"), ("#bar {", "bar"), ("#legend {", "legend")):
        ok(frag in mq, f"the breakpoint restyles the {label}")
    ok("#head .sub { display: none; }" in mq, "head: the subtitle gives way")
    ok(re.search(r"#head h1 \{[^}]*font-size: 1[0-9]px", mq) is not None,
       "head: the title is set smaller")
    ok("display: flex" in mq.split("#head {", 1)[-1].split("}", 1)[0]
       and "flex-wrap: wrap" in mq.split("#head {", 1)[-1].split("}", 1)[0],
       "head: date and counts share one wrapped row")
    for frag in ("left: 0; right: 0",):
        ok(mq.count(frag) >= 2, "head and bar span the full width", frag)
    ok("#row { display: flex;" in html and "flex-wrap: wrap" in html,
       "the bar row wraps rather than overflowing")
    ok(re.search(r"button \{[^}]*min-height: 40px", mq) is not None,
       "every control keeps a 40 px touch target")
    ok(".spacer { display: none; }" in mq, "the bar drops the spacer that forced one line")
    ok('.sp[data-s="0.5"], .sp[data-s="2"] { display: none; }' in html,
       "the two intermediate speeds go on a very narrow screen")
    ok('data-s="1"' in html and 'data-s="4"' in html, "1x and 4x survive")
    ok('class="md on" data-m="prop"' in html and 'data-m="compact"' in html,
       "proportional and compact stay")
    legend_mq = mq.split("#legend {", 1)[-1].split("}", 1)[0]
    ok("max-height: 50vh" in legend_mq and "max-width: calc(100vw" in legend_mq,
       "legend: an overlay of at most half the screen, scrolling inside itself")
    ok("var legPref = stored(LKEY)" in js
       and "legPref === null ? window.innerWidth > MOBILE_W" in js,
       "legend: folded by default on a narrow screen, a stored choice beating that")
    ok('store(LKEY,' in js, "legend: the fold is remembered")
    ok(re.search(r"#crawl h2 \{ font-size: 2[0-9]px", mq) is not None
       and re.search(r"#crawl p \{ font-size: 1[0-9]px", mq) is not None,
       "the opening is set down to phone sizes")
    ok("#skip { right: 10px; bottom: 10px;" in mq, "the skip button stays in reach")

    print("\n== fit: the picture takes what the panels leave")
    fit = js.split("function pads()", 1)[-1].split("function resize()", 1)[0]
    ok(bool(fit), "the keep-out zones are computed in one place")
    ok("getBoundingClientRect" in fit,
       "the zones are measured off the panels, not assumed")
    for frag in ("330", "padR", "W > 900"):
        ok(frag not in fit, f"no fixed desktop column left in the fit: {frag}")
    ok("narrow()" in fit, "the fit knows the two layouts apart")
    ok("legendOpen" in fit, "folding the legend still hands its column back")
    ok(re.search(r"legEl\.style\.top = narrow\(\)", js) is not None,
       "the overlay legend is seated under the head plate it measured")
    ok("window.addEventListener(\"resize\", resize)" in js, "the fit re-runs on resize")
    ok("rotate" not in js.split("function pads()", 1)[-1].split("function step", 1)[0],
       "portrait is fitted, not turned")
    ok('cv.addEventListener("pointerdown"' in js and 'ev.pointerType !== "touch"' in js,
       "a tap opens the tooltip a touch screen cannot hover for")
    ok('cv.addEventListener("pointermove"' in js and 'ev.pointerType === "touch"' in js,
       "the hover path stays with the pointer that has one")
    ok("if (!best) { hideTip(); return false; }" in js,
       "a tap on empty space closes the tooltip again")


def check_selfcontained(html: str) -> None:
    print("\n== self-contained")
    urls = sorted(set(re.findall(r"https?://[^\s\"'<>)]+", html)))
    ok(urls == [REPO_URL], "the repo link is the only address in the document", str(urls[:4]))
    for bad in ("<img", "<audio", "<video", "<iframe", "<link", "@import", "@font-face",
                " src=", "fetch(", "XMLHttpRequest", "importScripts", "new Image("):
        ok(bad not in html, f"nothing loaded: {bad.strip()}")


def load_payload(html: str) -> dict:
    blob = re.search(r'<script id="graph-data" type="application/json">(.*?)</script>',
                     html, re.S).group(1)
    return json.loads(blob.replace("<\\/", "</"))


def check_payload(d: dict, graph: dict) -> None:
    print("\n== embedded JSON")
    n_, e_ = d["nodes"], d["edges"]
    ok(True, "JSON parses", f"{len(n_)} nodes, {len(e_)} edges")
    ok(all(0 <= a < len(n_) and 0 <= b < len(n_) for a, b, *_ in e_), "edge indices in range")
    ok(len({(min(a, b), max(a, b)) for a, b, *_ in e_}) == len(e_), "no duplicate edges")
    ok(not any(a == b for a, b, *_ in e_), "no self edges")
    kinds = [e for e in e_ if len(e) > 2]
    ok(all(e[2] in (1, 2) for e in kinds), "edge kinds valid", f"{len(kinds)} supersession edges")
    ok(all(set(x) <= {"t", "d", "g", "s", "p", "r", "x", "y", "k", "cr", "c",
                      "lx", "ly", "px", "py", "qx", "qy"} for x in n_), "node fields known")
    ok(all(x["g"] in {p[0] for p in d["palette"]} for x in n_), "groups covered by the palette")
    ok(all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", x["d"]) for x in n_), "date fields well formed")

    imp = d.get("impact", {})
    ok(isinstance(imp.get("k"), int) and 0 <= imp["k"] < len(n_), "impact: DORA index valid",
       n_[imp["k"]]["t"] if isinstance(imp.get("k"), int) else "")
    ok(imp.get("dur", 0) > 0.5, "impact: duration set", str(imp.get("dur")))
    ok(imp.get("reach", 0) > 0, "impact: ring reach set", str(imp.get("reach")))
    stock = [i for i, x in enumerate(n_) if "px" in x]
    ok(bool(stock), "impact: pre-layout present", f"{len(stock)} bodies")
    ok(all(n_[i]["d"] < imp["d"] for i in stock), "impact: only stock older than DORA")
    ok(all("lx" in x and "ly" in x for x in n_ if x.get("k")), "containers carry label offsets")

    print("\n== page against data/graph.json")
    g_nodes, g_edges, meta = graph["nodes"], graph["edges"], graph["meta"]
    ok(len(n_) == len(g_nodes), "node count matches", f"{len(n_)} vs {len(g_nodes)}")
    ok(len(e_) == len(g_edges), "edge count matches", f"{len(e_)} vs {len(g_edges)}")
    ok(meta["counts"]["nodes"] == len(g_nodes) and meta["counts"]["edges"] == len(g_edges),
       "graph.json meta.counts consistent")
    expect = {(g["title"].split(" (")[0].strip() if g["kind"] == "container" else g["title"])
              for g in g_nodes}
    ok({x["t"] for x in n_} == expect, "title set matches")
    ok([x["d"] for x in n_] == [g["date"] for g in g_nodes], "dates match, in order")
    ok([x["g"] for x in n_] == [g["group"] for g in g_nodes], "groups match, in order")
    ok(sum(1 for x in n_ if x.get("k")) == meta["counts"]["containers"], "container count matches")
    ok([p[0] for p in d["palette"]] == [p["key"] for p in meta["palette"]], "palette carried over")
    ok(d.get("generated") == meta["generated"], "generated date carried over",
       f"{d.get('generated')} vs {meta['generated']}")
    ok(d.get("t0") == meta["timeline"]["start"], "timeline start carried over")

    index = {g["id"]: i for i, g in enumerate(g_nodes)}
    want = {(min(index[g["source"]], index[g["target"]]),
             max(index[g["source"]], index[g["target"]])): g["type"]
            for g in g_edges}
    got = {(min(a, b), max(a, b)): (kk[0] if kk else 0) for a, b, *kk in e_}
    ok(set(want) == set(got), "edge pairs match")
    want_sup = {k: v for k, v in want.items() if v.startswith("superseded")}
    got_sup = {k: v for k, v in got.items() if v}
    ok(set(want_sup) == set(got_sup)
       and all(got_sup[k] == (1 if want_sup[k] == "superseded-full" else 2) for k in want_sup),
       "supersession edges match by type", f"{len(got_sup)} edges")


# Edge kinds that rest on a curation decision or on a corpus field rather than on a
# plain cross-reference. Every one of them has to be named in meta.assumptions.
EXPLAINED_TYPES = {"prepares", "curated", "concretises", "implements",
                   "superseded-full", "superseded-partial"}


def check_assumptions(graph: dict) -> None:
    print("\n== assumptions (meta.assumptions)")
    meta = graph["meta"]
    ok(meta.get("schema", 0) >= 2, "schema >= 2 (carries meta.assumptions)", str(meta.get("schema")))
    a = meta.get("assumptions")
    ok(isinstance(a, dict) and {"date_overrides", "size_estimates", "curated_edges"} <= set(a),
       "assumptions block complete")
    if not isinstance(a, dict):
        return

    ids = {n["id"] for n in graph["nodes"]}
    by_id = {n["id"]: n for n in graph["nodes"]}

    missing = sorted(k for k in a["date_overrides"] if k not in ids)
    ok(not missing, "every dated-over node exists", str(missing[:3]))
    ok(all(set(v) == {"date", "reason"} and v["reason"] for v in a["date_overrides"].values()),
       "date overrides carry date and reason", f"{len(a['date_overrides'])} entries")
    wrong = sorted(k for k, v in a["date_overrides"].items()
                   if k in by_id and by_id[k]["date"] != v["date"])
    ok(not wrong, "dated-over nodes actually carry that date", str(wrong[:3]))

    missing = sorted(k for k in a["size_estimates"] if k not in ids)
    ok(not missing, "every size-estimated node exists", str(missing[:3]))
    ok(all(v.get("basis") in {"pages", "extrapolated"} and v.get("detail")
           for v in a["size_estimates"].values()),
       "size estimates carry basis and detail", f"{len(a['size_estimates'])} entries")
    flagged = {n["id"] for n in graph["nodes"] if n.get("size_estimated")}
    ok(set(a["size_estimates"]) == flagged, "size estimates match the size_estimated flag",
       f"{len(a['size_estimates'])} vs {len(flagged)} nodes")

    pairs = {tuple(sorted((e["source"], e["target"]))): e["type"] for e in graph["edges"]}
    curated = a["curated_edges"]
    ok(all(c.get("reason") and c.get("type") for c in curated),
       "curated edges carry type and reason", f"{len(curated)} entries")
    absent = [f"{c['source']} -> {c['target']}" for c in curated
              if tuple(sorted((c["source"], c["target"]))) not in pairs]
    ok(not absent, "every curated edge is present in edges", str(absent[:3]))
    mistyped = [f"{c['source']} -> {c['target']}" for c in curated
                if tuple(sorted((c["source"], c["target"]))) in pairs
                and pairs[tuple(sorted((c["source"], c["target"])))] != c["type"]]
    ok(not mistyped, "curated edge types agree with edges", str(mistyped[:3]))
    listed = {tuple(sorted((c["source"], c["target"]))) for c in curated}
    unexplained = sorted(f"{k[0]} -> {k[1]} ({t})" for k, t in pairs.items()
                         if t in EXPLAINED_TYPES and k not in listed)
    ok(not unexplained, "every non-plain edge is explained in curated_edges",
       str(unexplained[:3]))


def layout_checks(d: dict, tag: str, coord: dict, present: list, clearance_want: float,
                  label_off: dict, owner: dict) -> None:
    n_ = d["nodes"]

    def rr(i: int) -> float:
        return n_[i].get("cr", n_[i]["r"])

    print(f"\n== geometry {tag}")
    units = [i for i in owner if i in coord and owner[i] in coord]
    ov = {"container_container": 0, "container_free": 0, "free_free": 0, "unit_unit": 0}
    for a in range(len(present) - 1):
        for b in range(a + 1, len(present)):
            i, j = present[a], present[b]
            if math.hypot(coord[i][0] - coord[j][0], coord[i][1] - coord[j][1]) < rr(i) + rr(j) - 1e-9:
                ci, cj = bool(n_[i].get("k")), bool(n_[j].get("k"))
                ov["container_container" if ci and cj else "free_free" if not ci and not cj
                   else "container_free"] += 1
    for a in range(len(units) - 1):
        for b in range(a + 1, len(units)):
            i, j = units[a], units[b]
            if math.hypot(coord[i][0] - coord[j][0], coord[i][1] - coord[j][1]) < n_[i]["r"] + n_[j]["r"] - 1e-9:
                ov["unit_unit"] += 1
    for k, v in ov.items():
        ok(v == 0, f"{tag}: 0 overlaps {k}", str(v))
    clear = min(math.hypot(coord[i][0] - coord[j][0], coord[i][1] - coord[j][1]) - rr(i) - rr(j)
                for a in range(len(present) - 1) for b in range(a + 1, len(present))
                for i, j in [(present[a], present[b])])
    ok(clear >= clearance_want, f"{tag}: wanted clearance between bodies held",
       f"min {clear:.2f} >= {clearance_want}")
    bad = [n_[m]["t"] for m in units
           if math.hypot(coord[m][0] - coord[owner[m]][0], coord[m][1] - coord[owner[m]][1])
           + n_[m]["r"] > n_[owner[m]]["cr"] + 1e-6]
    ok(not bad, f"{tag}: 0 containment violations", str(bad[:3]))

    boxes = []
    for i in present:
        if not n_[i].get("k"):
            continue
        ox, oy = label_off[i]
        w, h = LABEL_CHAR_W * LABEL_FS * len(n_[i]["t"]), LABEL_FS * 1.2
        cx, cy = coord[i][0] + ox, coord[i][1] + oy
        boxes.append((n_[i]["t"], cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
    clash = [(boxes[a][0], boxes[b][0])
             for a in range(len(boxes) - 1) for b in range(a + 1, len(boxes))
             if boxes[a][1] < boxes[b][3] and boxes[b][1] < boxes[a][3]
             and boxes[a][2] < boxes[b][4] and boxes[b][2] < boxes[a][4]]
    ok(not clash, f"{tag}: 0 label overlaps", str(clash[:2]))
    inside = all(abs(coord[i][0] + label_off[i][0]) <= d["extent"][0] / 2 + 1e-6
                 and abs(coord[i][1] + label_off[i][1]) <= d["extent"][1] / 2 + 1e-6
                 for i in present if n_[i].get("k"))
    ok(inside, f"{tag}: labels inside the extent")


def check_geometry(d: dict) -> None:
    n_, e_ = d["nodes"], d["edges"]
    owner = {i: x["c"] for i, x in enumerate(n_) if "c" in x}
    bodies = [i for i, x in enumerate(n_) if x.get("k") or i not in owner]
    stock = [i for i, x in enumerate(n_) if "px" in x]

    end_coord = {i: (x["x"], x["y"]) for i, x in enumerate(n_)}
    end_labels = {i: (x.get("lx", 0.0), x.get("ly", 0.0)) for i, x in enumerate(n_)}
    layout_checks(d, "final layout", end_coord, bodies, 8.5, end_labels, owner)

    pre_coord = {i: (n_[i]["px"], n_[i]["py"]) for i in stock}
    for m, ci in owner.items():
        if ci in pre_coord:
            pre_coord[m] = (n_[m]["x"] + pre_coord[ci][0] - n_[ci]["x"],
                            n_[m]["y"] + pre_coord[ci][1] - n_[ci]["y"])
    pre_labels = {i: (n_[i].get("qx", n_[i].get("lx", 0.0)), n_[i].get("qy", n_[i].get("ly", 0.0)))
                  for i in stock}
    layout_checks(d, "pre-impact", pre_coord, sorted(stock), 4.5, pre_labels, owner)

    print("\n== sizes")
    ok(sorted({x["r"] for i, x in enumerate(n_) if i in owner}) == [2.5],
       "unit dots uniform at 2.5 px")
    small = min(x["cr"] for x in n_ if x.get("k"))
    free_r = [x["r"] for i, x in enumerate(n_) if not x.get("k") and i not in owner]
    ok(max(free_r) <= 0.75 * small + 1e-9, "free nodes <= 0.75 x smallest container",
       f"{max(free_r)} <= {0.75 * small:.2f}")

    print("\n== connectivity")
    deg: dict[int, int] = {}
    adj: dict[int, list[int]] = {i: [] for i in bodies}
    link: dict[int, set[int]] = {i: set() for i in bodies}
    for a, b, *_ in e_:
        ra, rb = owner.get(a, a), owner.get(b, b)
        if ra == rb:
            continue
        deg[ra] = deg.get(ra, 0) + 1
        deg[rb] = deg.get(rb, 0) + 1
        adj[ra].append(rb)
        adj[rb].append(ra)
        link[ra].add(rb)
        link[rb].add(ra)
    edgeless = [n_[i]["t"] for i in bodies if deg.get(i, 0) == 0]
    ok(not edgeless, "no edgeless object", str(edgeless))
    seen, stack = {bodies[0]}, [bodies[0]]
    while stack:
        u = stack.pop()
        for v in adj[u]:
            if v not in seen:
                seen.add(v)
                stack.append(v)
    ok(len(seen) == len(bodies), "graph is one component", f"{len(seen)}/{len(bodies)}")

    print("\n== distance guard rail (1.5 x DORA radius)")
    dora = next(i for i in bodies if n_[i]["t"] == "DORA")
    budget = 1.5 * n_[dora].get("cr", n_[dora]["r"])
    worst = []
    for i in bodies:
        if not link[i]:
            continue
        s = min(math.hypot(end_coord[i][0] - end_coord[j][0], end_coord[i][1] - end_coord[j][1])
                - n_[i].get("cr", n_[i]["r"]) - n_[j].get("cr", n_[j]["r"]) for j in link[i])
        worst.append((s, n_[i]["t"]))
    worst.sort(reverse=True)
    over = [w for w in worst if w[0] > budget + 0.5]
    ok(worst[0][0] <= 2.0 * budget, "no object far outside the guard rail",
       f"max {worst[0][0]:.1f} ({worst[0][1][:38]}), budget {budget:.1f}")
    ok(not over, "no body over the budget",
       ", ".join(f"{t[:28]} {s:.1f}" for s, t in over[:3]))


# Everything a README host is allowed to strip: the preview has to survive sanitising
# untouched, so it may carry none of it.
SVG_FORBIDDEN_TAGS = ("script", "style", "image", "foreignObject", "use", "a",
                      "animate", "set", "iframe")
SVG_FORBIDDEN_TEXT = ("href", "xlink", "url(", "@import", "data:", "<!ENTITY",
                      "javascript:", "class=")


def load_svg(path: Path, name: str, cap: int) -> tuple[str, object] | tuple[None, None]:
    """Open one of the still images and clear it of anything a host may strip."""
    print(f"\n== {name}")
    ok(path.exists(), f"{path} present")
    if not path.exists():
        return None, None
    raw = path.read_text(encoding="utf-8")
    size = len(raw.encode("utf-8"))
    ok(size < cap, f"under {cap // 1000} kB", f"{size / 1024:.0f} kB")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        ok(False, "well-formed XML", str(exc))
        return None, None
    ok(True, "well-formed XML")
    ok(root.tag == f"{{{SVG_NS}}}svg", "root element is <svg>", root.tag)
    for tag in SVG_FORBIDDEN_TAGS:
        ok(not any(True for _ in root.iter(f"{{{SVG_NS}}}{tag}")), f"no <{tag}> element")
    for frag in SVG_FORBIDDEN_TEXT:
        ok(frag not in raw, f"nothing that resolves elsewhere: {frag}")
    urls = sorted(set(re.findall(r"https?://[^\s\"'<>)]+", raw)))
    ok(urls == [SVG_NS], "the SVG namespace is the only URL in the file", str(urls[:4]))
    return raw, root


def svg_frame(root) -> tuple[float, float, tuple, str]:
    """viewBox, size and the painted ground — the three things a standalone file owes."""
    view = [float(v) for v in (root.get("viewBox") or "").split()]
    ok(len(view) == 4 and view[2] > 0 and view[3] > 0, "viewBox present and non-empty",
       root.get("viewBox"))
    if len(view) != 4:
        return 0.0, 0.0, (0.0, 0.0, 0.0, 0.0), ""
    w, h = float(root.get("width", 0)), float(root.get("height", 0))
    ok(w > 0 and h > 0, "explicit width and height on the root", f"{w:g} x {h:g}")
    ok(abs(view[2] - w) < 1e-6 and abs(view[3] - h) < 1e-6,
       "viewBox agrees with width/height")
    painted = [e for e in root if e.tag not in (f"{{{SVG_NS}}}title", f"{{{SVG_NS}}}desc")]
    first = painted[0] if painted else None
    ground = (first.get("fill") or "") if first is not None else ""
    ok(first is not None and first.tag == f"{{{SVG_NS}}}rect"
       and abs(float(first.get("x", 1e9)) - view[0]) < 0.5
       and abs(float(first.get("y", 1e9)) - view[1]) < 0.5
       and float(first.get("width", 0)) >= w and float(first.get("height", 0)) >= h
       and re.fullmatch(r"#[0-9a-fA-F]{6}", ground) is not None,
       "the ground is a painted full-bleed rectangle, not transparency", ground)
    return w, h, (view[0], view[1], view[0] + w, view[1] + h), ground


def svg_text_boxes(root, ground: str) -> dict:
    """Every text element with its box, the colour it is actually seen in, and the
    contrast WCAG asks of a text that size and weight."""
    all_text = list(root.iter(f"{{{SVG_NS}}}text"))
    styled = [t for t in all_text
              if float(t.get("font-size", 0)) > 0 and t.get("font-family")
              and re.fullmatch(r"#[0-9a-fA-F]{6}", t.get("fill") or "")]
    ok(len(styled) == len(all_text) and bool(styled),
       "every text carries its own font, size and literal fill",
       f"{len(styled)}/{len(all_text)} text elements")
    out = {}
    for t in styled:
        fs, weight = float(t.get("font-size")), int(t.get("font-weight", 400))
        tw = text_width(t.text or "", fs)
        x, y = float(t.get("x", 0)), float(t.get("y", 0))
        anchor = t.get("text-anchor", "start")
        x0 = x - tw / 2 if anchor == "middle" else x - tw if anchor == "end" else x
        out[t] = ((x0, y - fs * 0.80, x0 + tw, y + fs * 0.25),
                  blend(t.get("fill"), ground, float(t.get("fill-opacity", 1.0))),
                  3.0 if fs >= 24 or (fs >= 18.66 and weight >= 600) else 4.5)
    return out


def group(root, gid: str) -> list:
    found = root.find(f".//{{{SVG_NS}}}g[@id='{gid}']")
    return list(found) if found is not None else []


def as_circles(elements) -> list[tuple[float, float, float]]:
    return [(float(c.get("cx", 0)), float(c.get("cy", 0)), float(c.get("r", 0)))
            for c in elements]


def check_contrast(boxes: dict, ground: str) -> None:
    """A backing copy is a text painted and stroked in the ground colour — it is what
    the visible text is read *through*, so it is measured as the halo it is, not as
    text. Every one of them has to be answered by a visible twin at the same spot,
    otherwise the file would carry a label nobody can see."""
    backing = {t for t in boxes
               if (t.get("fill") or "").lower() == ground.lower() and t.get("stroke")}
    visible = {t for t in boxes if t not in backing}
    seats = {(t.text, t.get("x"), t.get("y")) for t in visible}
    orphan = [t.text for t in backing if (t.text, t.get("x"), t.get("y")) not in seats]
    ok(not orphan, "every halo is answered by a visible text", str(orphan[:3]))
    # Light text on a dark ground: measuring against the darkest paint in the file is
    # the conservative reading — the panels only ever sit lighter than it.
    scored = sorted((contrast_ratio(boxes[t][1], ground) - boxes[t][2],
                     boxes[t][1], boxes[t][2]) for t in visible)
    ok(bool(scored) and scored[0][0] >= 0, "every text clears its contrast floor",
       f"worst {scored[0][1]}: {scored[0][0] + scored[0][2]:.2f} >= {scored[0][2]}"
       if scored else "")


def check_labels_free(boxes: dict, texts: list, circles: list, blocks: list,
                      what: str) -> None:
    """The three ways an act name can stop naming its own circle."""
    lb = [(t.text, boxes[t][0]) for t in texts if t in boxes]
    clash = [(lb[i][0], lb[j][0]) for i in range(len(lb) - 1) for j in range(i + 1, len(lb))
             if boxes_overlap(lb[i][1], lb[j][1])]
    ok(not clash, "no label overlaps another label", str(clash[:2]))
    on_node = sorted({name for name, b in lb for c in circles if box_hits_circle(b, c)})
    ok(not on_node, "no label sits on a circle or a dot", str(on_node[:4]))
    on_block = sorted({name for name, b in lb for p in blocks if boxes_overlap(b, p)})
    ok(not on_block, f"no label runs under {what}", str(on_block[:3]))


def check_preview(path: Path, graph: dict) -> None:
    raw, root = load_svg(path, "preview image", 400_000)
    if root is None:
        return
    print("\n== preview: standalone geometry")
    w, h, box_v, ground = svg_frame(root)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", ground):
        return          # without a known ground the readability pass has no reference
    ok(1.15 <= w / h <= 2.15, "aspect in the band a README column reads well",
       f"{w / h:.3f}")

    print("\n== preview: drawn against data/graph.json")
    circles = as_circles(root.iter(f"{{{SVG_NS}}}circle"))
    ok(len(circles) == len(graph["nodes"]), "one circle drawn per graph node",
       f"{len(circles)} vs {len(graph['nodes'])}")
    acts = as_circles(group(root, "akte"))
    want = {n["title"].split(" (")[0].strip()
            for n in graph["nodes"] if n["kind"] == "container"}
    ok(len(acts) == len(want), "one ring per act", f"{len(acts)} vs {len(want)}")
    texts = group(root, "beschriftung")
    ok({t.text for t in texts} == want, "every act circle carries its label",
       f"{len(texts)} labels")
    halos = group(root, "beschriftung-halo")
    ok(len(halos) == len(texts) and [t.text for t in halos] == [t.text for t in texts],
       "each label is backed by its own halo copy", f"{len(halos)} halos")

    print("\n== preview: readability")
    boxes = svg_text_boxes(root, ground)
    outside = [t.text for t, (b, _, _) in boxes.items() if not box_inside(b, box_v)]
    ok(not outside, "no text runs out of the viewBox", str(outside[:3]))
    off = [f"{cx:.0f},{cy:.0f}" for cx, cy, r in circles
           if not box_inside((cx - r, cy - r, cx + r, cy + r), box_v)]
    ok(not off, "every node sits inside the viewBox", str(off[:3]))
    # The still carries no chrome: it is only ever seen in the README, which names the
    # picture and prints the rank legend beside it, so a title plate and a legend panel
    # would repeat that and cost the graph the room. Everything the file owes a reader
    # standing alone is in <title> and <desc>, which no plate can crowd.
    ok(not group(root, "rahmen"), "no chrome group left in the still")
    ok(not [r for r in root.iter(f"{{{SVG_NS}}}rect") if r.get("rx")],
       "no panel or swatch: background, edges, circles, dots and act labels only")
    head = [t.text for t in root
            if t.tag in (f"{{{SVG_NS}}}title", f"{{{SVG_NS}}}desc")]
    ok(len(head) == 2 and all(head), "the file still names itself for a screen reader",
       f"{len(head)} elements")

    print("\n== preview: act labels stand free")
    check_labels_free(boxes, texts, circles, [], "chrome")
    check_contrast(boxes, ground)


# GitHub's social preview template: 1280 x 640, and a 40 pt guard around anything that
# matters because some contexts crop the card — 80 px per edge at this pixel size.
CARD_W, CARD_H, CARD_SAFE = 1280.0, 640.0, 80.0


def check_card(path: Path, graph: dict) -> None:
    raw, root = load_svg(path, "social preview card", 400_000)
    if root is None:
        return
    print("\n== card: GitHub's card format")
    w, h, box_v, ground = svg_frame(root)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", ground):
        return
    ok(w == CARD_W and h == CARD_H, "1280 x 640 exactly", f"{w:g} x {h:g}")
    ok(box_v == (0.0, 0.0, CARD_W, CARD_H), "viewBox anchored at 0 0",
       root.get("viewBox"))
    safe = (CARD_SAFE, CARD_SAFE, CARD_W - CARD_SAFE, CARD_H - CARD_SAFE)

    circles = as_circles(root.iter(f"{{{SVG_NS}}}circle"))
    ok(len(circles) == len(graph["nodes"]), "one circle drawn per graph node",
       f"{len(circles)} vs {len(graph['nodes'])}")
    acts = as_circles(group(root, "akte"))
    want = {n["title"].split(" (")[0].strip()
            for n in graph["nodes"] if n["kind"] == "container"}
    ok(len(acts) == len(want), "one ring per act", f"{len(acts)} vs {len(want)}")
    texts = group(root, "beschriftung")
    halos = group(root, "beschriftung-halo")
    named = [t.text for t in texts]
    ok(named and set(named) <= want, "the named acts are real acts", ", ".join(named))
    ok(len(halos) == len(texts), "each label is backed by its own halo copy")

    print("\n== card: 40 pt safe area held")
    boxes = svg_text_boxes(root, ground)
    out_text = [t.text for t, (b, _, _) in boxes.items() if not box_inside(b, safe)]
    ok(not out_text, "no text reaches into the guard", str(out_text[:3]))
    out_act = [f"{cx:.0f},{cy:.0f}" for cx, cy, r in acts
               if not box_inside((cx - r, cy - r, cx + r, cy + r), safe)]
    ok(not out_act, "no act circle reaches into the guard", str(out_act[:3]))
    swatches = [(float(r.get("x", 0)), float(r.get("y", 0)),
                 float(r.get("x", 0)) + float(r.get("width", 0)),
                 float(r.get("y", 0)) + float(r.get("height", 0)))
                for r in group(root, "rahmen") if r.tag == f"{{{SVG_NS}}}rect"]
    ok(all(box_inside(s, safe) for s in swatches),
       "no colour chip reaches into the guard", f"{len(swatches)} chips")
    off = [f"{cx:.0f},{cy:.0f}" for cx, cy, r in circles
           if not box_inside((cx - r, cy - r, cx + r, cy + r), box_v)]
    ok(not off, "every node still sits inside the card", str(off[:3]))

    print("\n== card: act labels stand free")
    chrome = [boxes[t][0] for t in group(root, "rahmen") if t in boxes]
    check_labels_free(boxes, texts, circles, chrome, "the title or the colour key")
    check_contrast(boxes, ground)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify the built page against the graph.")
    ap.add_argument("--graph", type=Path, default=Path("data/graph.json"),
                    help="metadata graph (default: %(default)s)")
    ap.add_argument("--html", type=Path, default=Path("docs/index.html"),
                    help="built page (default: %(default)s)")
    ap.add_argument("--svg", type=Path, default=Path("docs/preview.svg"),
                    help="built preview image (default: %(default)s)")
    ap.add_argument("--card", type=Path, default=Path("docs/social-card.svg"),
                    help="built social preview card (default: %(default)s)")
    args = ap.parse_args(argv)

    html = args.html.read_text(encoding="utf-8")
    graph = json.loads(args.graph.read_text(encoding="utf-8"))

    check_file(html)
    js = check_js(html)
    check_opening(html, js)
    check_head(html)
    check_legend(html, js)
    check_glyphs(html, js)
    check_mobile(html, js)
    check_selfcontained(html)
    payload = load_payload(html)
    check_payload(payload, graph)
    check_assumptions(graph)
    check_geometry(payload)
    check_preview(args.svg, graph)
    check_card(args.card, graph)

    print("\n" + ("ALL CHECKS PASSED" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
