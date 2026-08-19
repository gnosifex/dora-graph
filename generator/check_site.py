#!/usr/bin/env python3
"""Verify docs/index.html against data/graph.json — file-based, no browser, no server.

Three families of checks:
  * the page:   placeholder replaced, script tags paired, JS structurally intact and
                still carrying the render decisions the design depends on
  * the payload the page embeds: field names, index ranges, date shapes, and agreement
                with data/graph.json on counts, titles and supersession edges
  * the geometry, for BOTH layouts (final picture and pre-impact pack): zero overlaps in
                every pair category, containment, uniform unit radii, the free-node cap,
                label collisions, connectivity, and the 1,5 x DORA distance guard rail

Exits non-zero as soon as one check fails.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

# has to stay in step with build_site's label model
LABEL_FS, LABEL_CHAR_W = 11.0, 0.60

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


def check_js(html: str) -> None:
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify the built page against the graph.")
    ap.add_argument("--graph", type=Path, default=Path("data/graph.json"),
                    help="metadata graph (default: %(default)s)")
    ap.add_argument("--html", type=Path, default=Path("docs/index.html"),
                    help="built page (default: %(default)s)")
    args = ap.parse_args(argv)

    html = args.html.read_text(encoding="utf-8")
    graph = json.loads(args.graph.read_text(encoding="utf-8"))

    check_file(html)
    check_js(html)
    payload = load_payload(html)
    check_payload(payload, graph)
    check_assumptions(graph)
    check_geometry(payload)

    print("\n" + ("ALL CHECKS PASSED" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
