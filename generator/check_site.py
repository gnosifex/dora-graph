#!/usr/bin/env python3
"""Verify docs/index.html against data/graph.json — file-based, no browser, no server.

Five families of checks:
  * the page:   placeholder replaced, script tags paired, JS structurally intact and
                still carrying the render decisions the design depends on, the opening
                sequence and its sound wired the way the design requires, and the whole
                document self-contained — no address but the repo link, nothing fetched
  * the payload the page embeds: field names, index ranges, date shapes, and agreement
                with data/graph.json on counts, titles and supersession edges
  * the geometry, for BOTH layouts (final picture and pre-impact pack): zero overlaps in
                every pair category, containment, uniform unit radii, the free-node cap,
                label collisions, connectivity, and the 1,5 x DORA distance guard rail
  * the preview image docs/preview.svg: well-formed XML, one circle per graph node,
                nothing that a README host would strip or refuse to fetch, and a
                readability pass — everything inside the viewBox, no label collisions,
                enough contrast against the painted ground

Exits non-zero as soon as one check fails.
"""

from __future__ import annotations

import argparse
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
    ok("setLineDash(full ? [6 * scale, 4 * scale] : [2.5 * scale, 5 * scale])" in js,
       "supersession edges still red dashed/dotted")
    ok("if (n.partial) ctx.setLineDash([4.5 * scale, 3.5 * scale])" in js,
       "estimate rings still dashed")
    ok('DUR = { prop: 45, compact: 30 }' in js, "proportional 45 s / compact 30 s")
    ok("nodes[IMP.k].born" in js and "IMP.reach" in js, "impact ring pulse present")
    return js


# The only address the page may carry. Everything else it needs it draws or generates
# itself, so the document works offline and asks nobody anything.
REPO_URL = "https://github.com/gnosifex/dora-graph"


def check_opening(html: str, js: str) -> None:
    print("\n== opening sequence")
    for frag in ('id="intro"', 'id="crawlwrap"', 'id="crawl"', 'id="stars"',
                 'id="skip"', 'id="intro-again"'):
        ok(frag in html, f"markup present: {frag}")
    ok("perspective:" in html and "rotateX(" in html, "text plane runs back in perspective")
    body = html.split('id="crawl"', 1)[-1].split("</div>", 1)[0]
    for line in ("Ein Blick auf die digitale operationale Resilienz",
                 "Die Geburt einer Regulatorik-Galaxie",
                 "Keine Rechtsberatung."):
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

    print("\n== sound")
    ok('id="sound"' in html and "♪ Ton" in html, "the bar carries the sound switch")
    ok("var soundOn = false" in js, "sound off by default")
    ok('soundBtn.addEventListener("click", function () { setSound(!soundOn); })' in js,
       "sound starts on a user gesture only")
    ok('document.addEventListener("pointerdown", arm)' in js,
       "a remembered switch still waits for a gesture")
    ok('store(SKEY,' in js and 'stored(SKEY) === "1"' in js, "sound state in localStorage")
    ok("createOscillator" in js and "createBuffer(" in js and "createBiquadFilter" in js,
       "the sound is generated in the browser")
    ok("MASTER_MAX = 0.16" in js and "lvl * MASTER_MAX" in js, "master level well under 1")
    ok("soundBtn.disabled = true" in js, "no sound under reduced motion")
    ok("impactRaw()" in js.split("function audioUpdate", 1)[-1].split("function setSound", 1)[0],
       "the swell follows the impact")


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


def check_preview(path: Path, graph: dict) -> None:
    print("\n== preview image")
    ok(path.exists(), f"{path} present")
    if not path.exists():
        return
    raw = path.read_text(encoding="utf-8")
    size = len(raw.encode("utf-8"))
    ok(size < 400_000, "under 400 kB", f"{size / 1024:.0f} kB")

    root = None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        ok(False, "well-formed XML", str(exc))
        return
    ok(True, "well-formed XML")
    ok(root.tag == f"{{{SVG_NS}}}svg", "root element is <svg>", root.tag)

    print("\n== preview: nothing to fetch, nothing to strip")
    for tag in SVG_FORBIDDEN_TAGS:
        ok(not any(True for _ in root.iter(f"{{{SVG_NS}}}{tag}")), f"no <{tag}> element")
    for frag in SVG_FORBIDDEN_TEXT:
        ok(frag not in raw, f"nothing that resolves elsewhere: {frag}")
    urls = sorted(set(re.findall(r"https?://[^\s\"'<>)]+", raw)))
    ok(urls == [SVG_NS], "the SVG namespace is the only URL in the file", str(urls[:4]))

    print("\n== preview: standalone geometry")
    view = [float(v) for v in (root.get("viewBox") or "").split()]
    ok(len(view) == 4 and view[2] > 0 and view[3] > 0, "viewBox present and non-empty",
       root.get("viewBox"))
    if len(view) != 4:
        return
    w, h = float(root.get("width", 0)), float(root.get("height", 0))
    ok(w > 0 and h > 0, "explicit width and height on the root", f"{w:g} x {h:g}")
    ok(abs(view[2] - w) < 1e-6 and abs(view[3] - h) < 1e-6,
       "viewBox agrees with width/height")
    ok(1.15 <= w / h <= 2.15, "aspect in the band a README column reads well",
       f"{w / h:.3f}")
    box_v = (view[0], view[1], view[0] + w, view[1] + h)

    painted = [e for e in root if e.tag not in (f"{{{SVG_NS}}}title", f"{{{SVG_NS}}}desc")]
    first = painted[0] if painted else None
    ground = (first.get("fill") or "") if first is not None else ""
    ok(first is not None and first.tag == f"{{{SVG_NS}}}rect"
       and abs(float(first.get("x", 1e9)) - view[0]) < 0.5
       and abs(float(first.get("y", 1e9)) - view[1]) < 0.5
       and float(first.get("width", 0)) >= w and float(first.get("height", 0)) >= h
       and re.fullmatch(r"#[0-9a-fA-F]{6}", ground) is not None,
       "the ground is a painted full-bleed rectangle, not transparency", ground)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", ground):
        return          # without a known ground the readability pass has no reference

    print("\n== preview: drawn against data/graph.json")
    circles = [(float(c.get("cx", 0)), float(c.get("cy", 0)), float(c.get("r", 0)))
               for c in root.iter(f"{{{SVG_NS}}}circle")]
    ok(len(circles) == len(graph["nodes"]), "one circle drawn per graph node",
       f"{len(circles)} vs {len(graph['nodes'])}")
    labels = root.find(f".//{{{SVG_NS}}}g[@id='beschriftung']")
    texts = list(labels) if labels is not None else []
    want = {n["title"].split(" (")[0].strip()
            for n in graph["nodes"] if n["kind"] == "container"}
    ok({t.text for t in texts} == want, "every act circle carries its label",
       f"{len(texts)} labels")
    halo_group = root.find(f".//{{{SVG_NS}}}g[@id='beschriftung-halo']")
    halos = list(halo_group) if halo_group is not None else []
    ok(len(halos) == len(texts) and [t.text for t in halos] == [t.text for t in texts],
       "each label is backed by its own halo copy", f"{len(halos)} halos")

    print("\n== preview: readability")
    all_text = list(root.iter(f"{{{SVG_NS}}}text"))
    styled = [t for t in all_text
              if float(t.get("font-size", 0)) > 0 and t.get("font-family")
              and re.fullmatch(r"#[0-9a-fA-F]{6}", t.get("fill") or "")]
    ok(len(styled) == len(all_text) and bool(styled),
       "every text carries its own font, size and literal fill",
       f"{len(styled)}/{len(all_text)} text elements")

    # box, seen colour and the contrast floor WCAG puts on a text of that weight
    boxes: dict[object, tuple] = {}
    for t in styled:
        fs, weight = float(t.get("font-size")), int(t.get("font-weight", 400))
        tw = text_width(t.text or "", fs)
        x, y = float(t.get("x", 0)), float(t.get("y", 0))
        anchor = t.get("text-anchor", "start")
        x0 = x - tw / 2 if anchor == "middle" else x - tw if anchor == "end" else x
        boxes[t] = ((x0, y - fs * 0.80, x0 + tw, y + fs * 0.25),
                    blend(t.get("fill"), ground, float(t.get("fill-opacity", 1.0))),
                    3.0 if fs >= 24 or (fs >= 18.66 and weight >= 600) else 4.5)

    outside = [t.text for t, (b, _, _) in boxes.items() if not box_inside(b, box_v)]
    ok(not outside, "no text runs out of the viewBox", str(outside[:3]))
    off = [f"{cx:.0f},{cy:.0f}" for cx, cy, r in circles
           if not box_inside((cx - r, cy - r, cx + r, cy + r), box_v)]
    ok(not off, "every node sits inside the viewBox", str(off[:3]))

    # the two chrome plates: the rounded rects in the frame group, told apart from the
    # legend swatches by their corner radius
    frame = root.find(f".//{{{SVG_NS}}}g[@id='rahmen']")
    plates = [(float(r.get("x", 0)), float(r.get("y", 0)),
               float(r.get("x", 0)) + float(r.get("width", 0)),
               float(r.get("y", 0)) + float(r.get("height", 0)))
              for r in (frame if frame is not None else []) if r.get("rx") == "12"]
    ok(len(plates) == 2, "title plate and legend plate found", f"{len(plates)} plates")

    print("\n== preview: act labels stand free")
    lb = [(t.text, boxes[t][0]) for t in texts if t in boxes]
    clash = [(lb[i][0], lb[j][0]) for i in range(len(lb) - 1) for j in range(i + 1, len(lb))
             if boxes_overlap(lb[i][1], lb[j][1])]
    ok(not clash, "no label overlaps another label", str(clash[:2]))
    on_node = sorted({name for name, b in lb for c in circles if box_hits_circle(b, c)})
    ok(not on_node, "no label sits on a circle or a dot", str(on_node[:4]))
    on_plate = sorted({name for name, b in lb for p in plates if boxes_overlap(b, p)})
    ok(not on_plate, "no label runs under the title or legend plate", str(on_plate[:3]))

    # Light text on a dark ground: measuring against the darkest paint in the file is
    # the conservative reading — the panels only ever sit lighter than it. The halo
    # copies are background-coloured by design; they are read through, not read.
    backing = set(halos)
    scored = sorted((contrast_ratio(seen, ground) - need, seen, need, t.text or "")
                    for t, (_, seen, need) in boxes.items() if t not in backing)
    ok(bool(scored) and scored[0][0] >= 0, "every text clears its contrast floor",
       f"worst {scored[0][1]}: {scored[0][0] + scored[0][2]:.2f} >= {scored[0][2]}"
       if scored else "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify the built page against the graph.")
    ap.add_argument("--graph", type=Path, default=Path("data/graph.json"),
                    help="metadata graph (default: %(default)s)")
    ap.add_argument("--html", type=Path, default=Path("docs/index.html"),
                    help="built page (default: %(default)s)")
    ap.add_argument("--svg", type=Path, default=Path("docs/preview.svg"),
                    help="built preview image (default: %(default)s)")
    args = ap.parse_args(argv)

    html = args.html.read_text(encoding="utf-8")
    graph = json.loads(args.graph.read_text(encoding="utf-8"))

    check_file(html)
    js = check_js(html)
    check_opening(html, js)
    check_selfcontained(html)
    payload = load_payload(html)
    check_payload(payload, graph)
    check_assumptions(graph)
    check_geometry(payload)
    check_preview(args.svg, graph)

    print("\n" + ("ALL CHECKS PASSED" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
