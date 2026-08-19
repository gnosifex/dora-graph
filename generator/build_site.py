#!/usr/bin/env python3
"""Build docs/index.html — the time-proportional timelapse — from data/graph.json.

This stage never touches the vault or the corpus. Its input is the metadata graph and
nothing else; everything here is geometry and rendering: the radius model, the layout
chain (force pass -> collision pass -> centralise -> compact -> leash -> dock hints ->
symmetrise -> aspect reshape -> pre-impact pack) and the canvas renderer that ships
inside the page.

Layout model: an act is a **container**, not a point. DORA, the twelve level-2
regulations and the four referenced acts are drawn as enclosing circles, and every
article, annex, section and recital of that act sits inside its own act's circle.
Everything that is a document in its own right - ESA guidelines, guidance, Q&As,
standards - is a free node placed by the force layout.

The solved picture is then tidied in fixed order: the documents are drawn home to the
acts they cite, no body may sit further from its nearest linked body than 1,5 x DORA's
radius, the acts are turned onto evenly spaced bearings around DORA, and the whole
arrangement is reshaped toward the aspect of the canvas it will be fitted into. The
replay opens with the pre-DORA stock packed around the middle: when DORA lands, it
drives that stock outward to the seats the layout gave it.

The layout is deterministic: the force pass runs off a fixed seed, so the same
graph.json always yields the same page.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

# The act every bearing is measured from, and the id build_site treats as the centre of
# the picture. It is a layout decision, not a corpus fact.
IMPACT_ID = "dora"

# Edge kinds the renderer draws apart, because they run backwards in time - the older
# instrument yields to DORA. Everything else is a plain line.
E_REF, E_SUPER, E_SUPER_PART = 0, 1, 2
SUPERSEDED_KIND = {"superseded-full": E_SUPER, "superseded-partial": E_SUPER_PART}

# Two containers the generic weighting does not carry far enough. KWG is a reference act
# whose edges nearly all run to its own units, so it scores low despite its size; the
# RTS-RMF circle is the second largest in the picture and belongs near the middle.
CENTRE_PULL = {"kwg": 0.5, "rts-rmf-2024-1774": 0.5}

# Neighbourhood hints: a colour group is seated next to the act it reads with. The
# standards already hang off RTS-RMF's articles through the "Ordnet Betrachtung an"
# edges, and the rank-3 supervisory layer (ESA/EBA guidelines, the MaRisk and BAIT
# circulars) is the national side of the picture, which is KWG's corner.
GROUP_HINTS = {"standard": "rts-rmf-2024-1774", "rang-3": "kwg"}
HINT_PULL = 0.55    # share of a real edge's spring strength


# ---------------------------------------------------------------------------
# geometry constants
# ---------------------------------------------------------------------------

R_UNIT = 2.5        # one uniform size for every "page" node, see SIZED_KINDS below
R_MIN = 2.5
# Hard design rule: no free document may ever look bigger than the smallest act. A
# binding regulation must not be dwarfed by the final report that prepared it, so the
# free volume nodes are capped at a fraction of the smallest container radius.
FREE_CAP_FACTOR = 0.75
MED_OF_CAP = 0.60   # the median free document sits here within the capped span
KNEE_FACTOR = 1.6   # compression starts at 1.6x the median, still below the cap
KNEE_SOFTNESS = 3.0
UNIT_GAP = 1.6      # clear space between two units inside a container
INNER_PAD = 5.0     # container wall clearance
BODY_GAP = 9.0      # clear space between containers / free nodes
DESIGN_W, DESIGN_H = 1700, 1040

# The force pass scales repulsion with body size, so the biggest acts get shoved to the
# rim — the opposite of what the picture should say. A body's place belongs to its role:
# a large act many documents point at reads as central, a small edge-poor node can have
# the margin. Every body is therefore drawn toward the centre of mass by a share of its
# distance, scaled by mass x connectedness, before the collision pass runs again.
CENTRE_GAIN = 0.30
# Two containers the generic weighting does not carry far enough. KWG is a reference act
# whose edges nearly all run to its own units, so it scores low despite its size; the
# RTS-RMF circle is the second largest in the picture and belongs near the middle.
CENTRE_PULL = {"kwg": 0.5, "rts-rmf-2024-1774": 0.5}

# Neighbourhood hints: a colour group is seated next to the act it reads with. The
# standards already hang off RTS-RMF's articles through the "Ordnet Betrachtung an"
# edges, and the rank-3 supervisory layer (ESA/EBA guidelines, the MaRisk and BAIT
# circulars) is the national side of the picture, which is KWG's corner.
GROUP_HINTS = {"standard": "rts-rmf-2024-1774", "rang-3": "kwg"}
HINT_PULL = 0.55    # share of a real edge's spring strength

# Free nodes are placed by repulsion, which leaves them further out than their links
# warrant. After the layout is solved they are walked back toward the bodies they link
# to, as far as BODY_GAP allows — the gap is the floor, this only removes slack.
COMPACT_ROUNDS = 26
COMPACT_STEP = 0.30

# Distance leash. No body may sit further from its nearest linked body than this share
# of DORA's radius, whatever it is: the compaction pass only walks free nodes home, so a
# container hanging on a single edge (Verordnung 1025/2012 -> RTS-RMF) used to keep the
# rim position the repulsion gave it. The leash applies to every body with an edge.
LEASH_FACTOR = 1.5
LEASH_ROUNDS = 26
LEASH_STEP = 0.45

# Radial symmetry. The force pass leaves the acts bunched on some bearings and empty on
# others. After it is solved the containers are nudged toward evenly spaced angles
# around DORA — radii untouched, so the backbone the edges built survives — and every
# other body is carried along by the angular delta of its neighbourhood, which keeps the
# group hints (standards by RTS-RMF, rank 3 by KWG) intact.
SYMMETRY_BLEND = 0.20
SYMMETRY_ROUNDS = 9

# The impact. Everything older than DORA starts packed around the spot DORA will hit and
# is driven out to its solved position when the circle lands.
PRE_SQUEEZE = 0.34   # start radius as a share of the solved radius
PRE_ROUNDS = 34
PRE_KEEP = 0.90      # per-round radial shrink, stopped by the collision pass
PRE_INSIDE = 0.80    # and never further out than this share of the body's solved radius
PRE_GAP = 5.0        # the waiting pack may sit tighter than the finished picture
IMPACT_SECONDS = 1.25

# Container labels are laid out in design units against a deliberately generous font box:
# the canvas clamps the rendered size at 13 px while positions scale freely, so a label
# that fits here can only get roomier on screen.
LABEL_FS = 11.0
LABEL_CHAR_W = 0.60
LABEL_PAD = 2.0

# The canvas is wide, the solved layout is nearly round, so the fit leaves a third of the
# screen empty. Widening the solved positions along x — positions only, radii untouched —
# can never create an overlap (every pair's dx grows, dy stays), so the picture may claim
# the width the viewport offers. Capped well below the canvas aspect: a mild ellipse
# still reads as balanced, a strong one would undo the radial symmetry.
# The target is the shape of the canvas the picture actually gets: the reference
# viewport minus the panels, the same arithmetic the page runs at runtime.
FIT_VIEWPORT = (1600.0, 1000.0)
ASPECT_TARGET = (FIT_VIEWPORT[0] - 30 - 330) / (FIT_VIEWPORT[1] - 104 - 96)
ASPECT_CAP = 1.45
ASPECT_ROUNDS = 3   # reshape, settle, measure again — the settle eats part of each turn

# ---------------------------------------------------------------------------
# sizes
# ---------------------------------------------------------------------------


def compute_radii(records: list[dict], cont_r: dict[int, float]) -> tuple[list[float], dict]:
    # The scale is anchored on the FREE sized documents only — containers are sized by
    # their packing, not by this — and the whole span is squeezed under the cap derived
    # from the smallest act. Area stays proportional to characters below the knee.
    smallest_container = min(cont_r.values()) if cont_r else 12.0
    cap = FREE_CAP_FACTOR * smallest_container
    target_med = MED_OF_CAP * cap
    # the knee must stay below the cap, otherwise the linear branch would run past it
    knee = min(KNEE_FACTOR * target_med, 0.96 * cap)

    free_sized = [i for i, r in enumerate(records) if r["sized"] and not r["hub"]]
    roots = sorted(math.sqrt(max(records[i]["size"], 1)) for i in free_sized)
    v_med = roots[len(roots) // 2] if roots else 1.0
    scale = target_med / v_med if v_med else 1.0

    def shape(v: float) -> float:
        if v <= knee:
            return min(max(v, R_MIN), cap)
        return min(knee + (cap - knee) * (1.0 - math.exp(-(v - knee) / max(knee * KNEE_SOFTNESS, 1e-3))), cap)

    radii = []
    for i, r in enumerate(records):
        if i in cont_r:
            radii.append(cont_r[i])          # containers carry their packing radius
        elif r["sized"] and not r["hub"]:
            radii.append(shape(scale * math.sqrt(max(r["size"], 1))))
        else:
            radii.append(R_UNIT)
    free_r = [radii[i] for i in free_sized]
    return radii, {
        "einheitsradius": R_UNIT,
        "einheitlich_klein": sum(1 for i, r in enumerate(records)
                                 if i not in cont_r and not (r["sized"] and not r["hub"])),
        "volumenbasiert_frei": len(free_r),
        "kleinster_container": round(smallest_container, 2),
        "deckel_frei": round(cap, 2),
        "zielmedian": round(target_med, 2),
        "knie": round(knee, 2),
        "min_frei": round(min(free_r), 2) if free_r else None,
        "median_frei": round(sorted(free_r)[len(free_r) // 2], 2) if free_r else None,
        "max_frei": round(max(free_r), 2) if free_r else None,
        "am_minimum": sum(1 for r in free_r if r <= R_MIN + 0.01),
        "nahe_deckel": sum(1 for r in free_r if r > cap - 0.2),
        "regel_eingehalten": bool(free_r) and max(free_r) <= smallest_container * FREE_CAP_FACTOR + 1e-9,
    }


# ---------------------------------------------------------------------------
# container packing
# ---------------------------------------------------------------------------

GOLDEN = math.pi * (3 - math.sqrt(5))


def phyllotaxis(n: int, unit_r: float, gap: float) -> tuple[list[tuple[float, float]], float]:
    """Sunflower packing of n equal discs; returns offsets and the enclosing radius."""
    if n == 0:
        return [], unit_r + INNER_PAD
    base = [
        (math.cos(GOLDEN * k) * math.sqrt(k + 0.5), math.sin(GOLDEN * k) * math.sqrt(k + 0.5))
        for k in range(n)
    ]
    need = 2 * unit_r + gap
    c = need
    if n > 1:
        closest = min(
            math.hypot(base[i][0] - base[j][0], base[i][1] - base[j][1])
            for i in range(n - 1)
            for j in range(i + 1, n)
        )
        c = need / closest if closest > 1e-9 else need
    pts = [(p[0] * c, p[1] * c) for p in base]
    reach = max(math.hypot(*p) for p in pts) if pts else 0.0
    return pts, reach + unit_r + INNER_PAD


# ---------------------------------------------------------------------------
# layout
# ---------------------------------------------------------------------------


def layout(n: int, edges: list[tuple[int, int]], radii: list[float], iterations: int = 260,
           hints: list[tuple[int, int]] | None = None):
    rnd = random.Random(20260819)
    size = 2600.0
    xs = [rnd.uniform(-size / 2, size / 2) for _ in range(n)]
    ys = [rnd.uniform(-size / 2, size / 2) for _ in range(n)]
    k = math.sqrt((size * size) / max(n, 1)) * 0.95
    k2 = k * k
    temp = size / 8.0
    cool = temp / (iterations + 1)
    for _ in range(iterations):
        dx = [0.0] * n
        dy = [0.0] * n
        for i in range(n - 1):
            xi, yi, ri = xs[i], ys[i], radii[i]
            for j in range(i + 1, n):
                ex, ey = xi - xs[j], yi - ys[j]
                d2 = ex * ex + ey * ey
                if d2 < 0.01:
                    ex, ey, d2 = rnd.uniform(-1, 1), rnd.uniform(-1, 1), 1.0
                # big bodies push harder, so containers claim their own room early
                f = k2 / d2 * (1.0 + (ri + radii[j]) / 30.0)
                fx, fy = ex * f, ey * f
                dx[i] += fx; dy[i] += fy
                dx[j] -= fx; dy[j] -= fy
        for a, b in edges:
            ex, ey = xs[a] - xs[b], ys[a] - ys[b]
            d = math.hypot(ex, ey) or 0.01
            f = d * d / k * 0.5
            fx, fy = ex / d * f, ey / d * f
            dx[a] -= fx; dy[a] -= fy
            dx[b] += fx; dy[b] += fy
        # neighbourhood hints: a one-sided spring that seats a group beside the act it
        # belongs to. Only the member moves — the target keeps the place its own edges
        # earned it, so a hint can bias the picture without rearranging its backbone.
        for a, t in hints or ():
            ex, ey = xs[a] - xs[t], ys[a] - ys[t]
            d = math.hypot(ex, ey) or 0.01
            f = d * d / k * 0.5 * HINT_PULL
            dx[a] -= ex / d * f; dy[a] -= ey / d * f
        for i in range(n):
            dx[i] -= xs[i] * 0.012
            dy[i] -= ys[i] * 0.012
            d = math.hypot(dx[i], dy[i]) or 1.0
            step = min(d, temp)
            xs[i] += dx[i] / d * step
            ys[i] += dy[i] / d * step
        temp -= cool
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    return [(xs[i] - cx, ys[i] - cy) for i in range(n)]


def fit_into_box(pos, w: float, h: float, margin: float = 30.0):
    xs = [q[0] for q in pos]
    ys = [q[1] for q in pos]
    spanx = (max(xs) - min(xs)) or 1.0
    spany = (max(ys) - min(ys)) or 1.0
    f = min((w - 2 * margin) / spanx, (h - 2 * margin) / spany)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    return [((q[0] - cx) * f, (q[1] - cy) * f) for q in pos]


def resolve_collisions(pos, radii, gap: float, rounds: int = 900, frozen=frozenset()):
    """Push overlapping bodies apart. `frozen` bodies hold their place and the other
    side of the pair yields for both — that is how a solved arrangement (the even ring
    of acts) survives a pass that is only meant to tidy the free nodes around it."""
    pts = [[x, y] for x, y in pos]
    n = len(pts)
    cell = (max(radii) * 2 + gap) if radii else 10.0
    for _ in range(rounds):
        grid: dict[tuple[int, int], list[int]] = {}
        for i in range(n):
            grid.setdefault((int(pts[i][0] // cell), int(pts[i][1] // cell)), []).append(i)
        moved = 0
        for i in range(n):
            gx, gy = int(pts[i][0] // cell), int(pts[i][1] // cell)
            for ox in (-1, 0, 1):
                for oy in (-1, 0, 1):
                    for j in grid.get((gx + ox, gy + oy), ()):
                        if j <= i:
                            continue
                        ex, ey = pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]
                        d = math.hypot(ex, ey)
                        need = radii[i] + radii[j] + gap
                        if d >= need:
                            continue
                        if d < 1e-6:
                            ex, ey, d = 1.0, 0.0, 1.0
                        fi, fj = i in frozen, j in frozen
                        if fi and fj:
                            continue
                        push = (need - d) / d * (1.0 if fi or fj else 0.5)
                        if not fi:
                            pts[i][0] -= ex * push; pts[i][1] -= ey * push
                        if not fj:
                            pts[j][0] += ex * push; pts[j][1] += ey * push
                        moved += 1
        if moved == 0:
            break
    remaining = sum(
        1
        for i in range(n - 1)
        for j in range(i + 1, n)
        if math.hypot(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]) < radii[i] + radii[j]
    )
    return pts, remaining


# ---------------------------------------------------------------------------
# centralisation
# ---------------------------------------------------------------------------


def centre_of_mass(pos, radii) -> tuple[float, float]:
    """Area-weighted centre, so the big circles decide where the middle is."""
    w = [r * r for r in radii]
    total = sum(w) or 1.0
    return (sum(p[0] * q for p, q in zip(pos, w)) / total,
            sum(p[1] * q for p, q in zip(pos, w)) / total)


def centralise(pos, radii, edges: list[tuple[int, int]], forced: dict[int, float]):
    """Pull bodies toward the centre of mass by a share of their distance.

    The share follows mass x connectedness: a big, well-linked container moves in, a
    small node with one edge barely moves, so the ranking of the picture matches the
    ranking of the corpus. `forced` overrides the retained fraction for named bodies.
    The result still has to survive a collision pass — this only sets the intent.
    """
    n = len(pos)
    deg = [0] * n
    for a, b in edges:
        deg[a] += 1
        deg[b] += 1
    score = [math.sqrt(radii[i]) * math.log1p(deg[i]) for i in range(n)]
    top = max(score) or 1.0
    rel = [s / top for s in score]
    mean = sum(rel) / n if n else 0.0
    # centred on the mean, so the pass redistributes instead of shrinking: above-average
    # bodies move in, below-average ones drift out, and the picture keeps its area —
    # a global squeeze would leave the collision pass unable to honour BODY_GAP
    cx, cy = centre_of_mass(pos, radii)
    out = []
    for i in range(n):
        keep = forced.get(i, 1.0 - CENTRE_GAIN * (rel[i] - mean))
        out.append([cx + (pos[i][0] - cx) * keep, cy + (pos[i][1] - cy) * keep])
    return out, (cx, cy)


def compact_free(pos, radii, edges: list[tuple[int, int]], movable: set[int], gap: float,
                 frozen=frozenset()):
    """Walk free nodes back toward the bodies they link to, then re-settle.

    The repulsion that keeps the layout readable also parks a lightly-linked document
    far from the act it belongs to. Each round pulls every movable node a short way
    toward its nearest linked body and hands the result to the collision pass, so the
    slack disappears but `gap` still decides how close anything may finally sit.
    """
    pts = [[q[0], q[1]] for q in pos]
    linked: dict[int, list[int]] = {i: [] for i in range(len(pts))}
    for a, b in edges:
        linked[a].append(b)
        linked[b].append(a)
    for _ in range(COMPACT_ROUNDS):
        for i in movable:
            peers = linked[i]
            if not peers:
                continue
            j = min(peers, key=lambda p: math.hypot(pts[p][0] - pts[i][0], pts[p][1] - pts[i][1]))
            ex, ey = pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]
            d = math.hypot(ex, ey) or 1.0
            slack = d - radii[i] - radii[j] - gap
            if slack <= 0:
                continue
            move = slack * COMPACT_STEP
            pts[i][0] += ex / d * move
            pts[i][1] += ey / d * move
        pts, _ = resolve_collisions(pts, radii, gap, frozen=frozen)
    return pts


def leash(pos, radii, edges: list[tuple[int, int]], budget: float, gap: float,
          frozen=frozenset()):
    """Pull every body that drifted away from its links back within `budget`.

    `compact_free` only walks the free nodes home, so a container that hangs on a single
    edge keeps whatever the repulsion pass gave it. This pass makes the rule general: any
    body whose nearest linked partner is further away than `budget` (rim to rim) is
    stepped toward that partner, and the collision pass decides how far it really gets.
    """
    pts = [[q[0], q[1]] for q in pos]
    linked: dict[int, list[int]] = {i: [] for i in range(len(pts))}
    for a, b in edges:
        linked[a].append(b)
        linked[b].append(a)

    def worst(p):
        out = []
        for i in range(len(p)):
            if not linked[i]:
                continue
            j = min(linked[i], key=lambda q: math.hypot(p[q][0] - p[i][0], p[q][1] - p[i][1]))
            out.append((math.hypot(p[j][0] - p[i][0], p[j][1] - p[i][1]) - radii[i] - radii[j], i, j))
        return out

    before = max((s for s, _, _ in worst(pts)), default=0.0)
    for _ in range(LEASH_ROUNDS):
        moved = 0
        for slack, i, j in worst(pts):
            if slack <= budget or i in frozen:
                continue
            ex, ey = pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]
            d = math.hypot(ex, ey) or 1.0
            step = (slack - budget) * LEASH_STEP
            pts[i][0] += ex / d * step
            pts[i][1] += ey / d * step
            moved += 1
        if not moved:
            break
        pts, _ = resolve_collisions(pts, radii, gap, frozen=frozen)
    after = worst(pts)
    return pts, {
        "richtwert": round(budget, 1),
        "max_vorher": round(before, 1),
        "max_nachher": round(max((s for s, _, _ in after), default=0.0), 1),
        "ueber_richtwert": sum(1 for s, _, _ in after if s > budget + 1e-6),
    }


def dock_hints(pos, radii, pairs, budget: float, gap: float, frozen=frozenset()):
    """Keep a hinted group seated next to its act after the ring has been turned.

    The hint is a bias in the force pass, and the passes after it answer only to real
    edges — a rank-3 circular that hangs on DORA would be walked to DORA's rim and would
    leave KWG's corner. This walks the hinted bodies back within the same distance the
    leash allows, so the seating survives without inventing an edge that is not there.
    """
    pts = [[q[0], q[1]] for q in pos]
    for _ in range(LEASH_ROUNDS):
        moved = 0
        for i, t in pairs:
            if i in frozen:
                continue
            ex, ey = pts[t][0] - pts[i][0], pts[t][1] - pts[i][1]
            d = math.hypot(ex, ey) or 1.0
            slack = d - radii[i] - radii[t]
            if slack <= budget:
                continue
            step = (slack - budget) * LEASH_STEP
            pts[i][0] += ex / d * step
            pts[i][1] += ey / d * step
            moved += 1
        if not moved:
            break
        pts, _ = resolve_collisions(pts, radii, gap, frozen=frozen)
    return pts


# ---------------------------------------------------------------------------
# radial symmetry
# ---------------------------------------------------------------------------


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def angular_gaps(pos, ks: list[int], centre) -> list[float]:
    """Bearing gaps between neighbouring bodies as seen from `centre`, in degrees."""
    if len(ks) < 2:
        return []
    ang = sorted(math.degrees(math.atan2(pos[k][1] - centre[1], pos[k][0] - centre[0])) % 360
                 for k in ks)
    return [(ang[(m + 1) % len(ang)] - ang[m]) % 360 for m in range(len(ang))]


def turn_toward_even(pos, ring: list[int], centre_k: int, blend: float):
    """One turn of the ring toward evenly spaced bearings, radii untouched.

    The force pass answers only to edges, so the acts end up bunched on a few bearings.
    Each container is turned part of the way toward an evenly spaced slot (the slot
    offset is the one that turns the ring least), and every other body inherits the
    angular shift of the containers it sits between — so a group seated next to an act
    travels with that act instead of being left behind.
    """
    cx, cy = pos[centre_k]
    ang = {k: math.atan2(pos[k][1] - cy, pos[k][0] - cx) % (2 * math.pi) for k in ring}
    order = sorted(ring, key=lambda k: ang[k])
    n = len(order)
    if n < 2:
        return [list(p) for p in pos]
    stepa = 2 * math.pi / n
    us = [ang[k] - m * stepa for m, k in enumerate(order)]
    phi0 = math.atan2(sum(math.sin(u) for u in us) / n, sum(math.cos(u) for u in us) / n)
    delta = {k: _wrap(phi0 + m * stepa - ang[k]) * blend for m, k in enumerate(order)}

    anchors = sorted((ang[k], delta[k]) for k in ring)

    def delta_at(a: float) -> float:
        a %= 2 * math.pi
        for m in range(len(anchors)):
            a0, d0 = anchors[m]
            a1, d1 = anchors[(m + 1) % len(anchors)]
            span = (a1 - a0) % (2 * math.pi)
            off = (a - a0) % (2 * math.pi)
            if off <= span or span < 1e-9:
                f = off / span if span > 1e-9 else 0.0
                return d0 + _wrap(d1 - d0) * min(f, 1.0)
        return 0.0

    out = []
    for i in range(len(pos)):
        if i == centre_k:
            out.append([pos[i][0], pos[i][1]])
            continue
        dx, dy = pos[i][0] - cx, pos[i][1] - cy
        r = math.hypot(dx, dy)
        if r < 1e-9:
            out.append([pos[i][0], pos[i][1]])
            continue
        a = math.atan2(dy, dx)
        na = a + (delta[i] if i in delta else delta_at(a))
        out.append([cx + r * math.cos(na), cy + r * math.sin(na)])
    return out


def symmetrise(pos, radii, ring: list[int], centre_k: int, gap: float):
    """Relax the ring toward even bearings in small turns.

    Turned in one go the ring drives bodies straight through each other, and the
    collision pass then blows the picture apart rather than tidying it. Small turns with
    a settle in between let the packing follow the rotation instead of fighting it.
    """
    pts = [[q[0], q[1]] for q in pos]
    for _ in range(SYMMETRY_ROUNDS):
        pts = turn_toward_even(pts, ring, centre_k, SYMMETRY_BLEND)
        pts, _ = resolve_collisions(pts, radii, gap)
    return pts


# ---------------------------------------------------------------------------
# the impact: where the pre-DORA stock waits
# ---------------------------------------------------------------------------


def pre_impact_layout(pos, radii, stock: list[int], centre, gap: float):
    """Pack the pre-DORA bodies tightly around the spot DORA will hit.

    Their solved bearings are kept and only the radii are squeezed, so when DORA lands
    every body has a straight way out to the place the layout gave it — the animation is
    a radial push, not a reshuffle. The collision pass decides how tight the pack gets.
    """
    cx, cy = centre
    pts = [[cx + (pos[k][0] - cx) * PRE_SQUEEZE, cy + (pos[k][1] - cy) * PRE_SQUEEZE]
           for k in stock]
    sub_r = [radii[k] for k in stock]
    ends = [math.hypot(pos[k][0] - cx, pos[k][1] - cy) for k in stock]
    pts, _ = resolve_collisions(pts, sub_r, gap)
    for _ in range(PRE_ROUNDS):
        for t in range(len(pts)):
            d = math.hypot(pts[t][0] - cx, pts[t][1] - cy)
            # never start further out than the body will end up: the push has to read as
            # outward for every body, so the cap beats the uniform shrink where they meet
            keep = min(PRE_KEEP, (PRE_INSIDE * ends[t] / d) if d > 1e-6 else PRE_KEEP)
            pts[t][0] = cx + (pts[t][0] - cx) * keep
            pts[t][1] = cy + (pts[t][1] - cy) * keep
        pts, _ = resolve_collisions(pts, sub_r, gap)
    out = {k: (pts[t][0], pts[t][1]) for t, k in enumerate(stock)}
    outward = sum(
        1 for t, k in enumerate(stock)
        if (pos[k][0] - pts[t][0]) * (pts[t][0] - cx) + (pos[k][1] - pts[t][1]) * (pts[t][1] - cy) > 0
    )
    reach = max((math.hypot(pts[t][0] - cx, pts[t][1] - cy) + sub_r[t]
                 for t in range(len(pts))), default=0.0)
    return out, {
        "koerper": len(stock),
        "radius_der_packung": round(reach, 1),
        "nach_aussen_gedrueckt": f"{outward}/{len(stock)}",
        "weg_median": round(sorted(math.hypot(pos[k][0] - out[k][0], pos[k][1] - out[k][1])
                                   for k in stock)[len(stock) // 2], 1) if stock else 0.0,
    }


# ---------------------------------------------------------------------------
# container labels
# ---------------------------------------------------------------------------


def label_box(text: str) -> tuple[float, float]:
    return LABEL_CHAR_W * LABEL_FS * len(text), LABEL_FS * 1.2


def place_labels(pts, rad, ks: list[int], text: dict[int, str]):
    """Seat every container label clear of the other labels and of the circles.

    Above the ring is the reading position; a label only leaves it when that spot is
    taken. The biggest act picks first, so the strongest circle keeps the natural place.
    """
    boxes: list[tuple[float, float, float, float]] = []
    out: dict[int, tuple[float, float]] = {}
    dirs = ((0, -1), (0, 1), (-1, -0.7), (1, -0.7), (-1, 0.7), (1, 0.7), (-1, 0), (1, 0))
    for k in sorted(ks, key=lambda q: -rad[q]):
        w, h = label_box(text[k])
        chosen = None
        for ring in range(7):
            for dx, dy in dirs:
                ox = dx * (rad[k] + 3.0 + w / 2 + ring * 4.0)
                oy = dy * (rad[k] + 3.0 + h / 2 + ring * 5.0)
                bx0, by0 = pts[k][0] + ox - w / 2, pts[k][1] + oy - h / 2
                box = (bx0, by0, bx0 + w, by0 + h)
                if any(box[0] < o[2] + LABEL_PAD and o[0] < box[2] + LABEL_PAD
                       and box[1] < o[3] + LABEL_PAD and o[1] < box[3] + LABEL_PAD for o in boxes):
                    continue
                hit = False
                for q in ks:
                    nx = min(max(pts[q][0], box[0]), box[2])
                    ny = min(max(pts[q][1], box[1]), box[3])
                    if math.hypot(pts[q][0] - nx, pts[q][1] - ny) < rad[q] + 1.0:
                        hit = True
                        break
                if hit:
                    continue
                chosen = (ox, oy, box)
                break
            if chosen:
                break
        if chosen is None:
            w2, h2 = w / 2, h / 2
            ox, oy = 0.0, -(rad[k] + 3.0 + h2 + 34.0)
            chosen = (ox, oy, (pts[k][0] + ox - w2, pts[k][1] + oy - h2,
                              pts[k][0] + ox + w2, pts[k][1] + oy + h2))
        out[k] = (chosen[0], chosen[1])
        boxes.append(chosen[2])
    clashes = sum(
        1 for a in range(len(boxes) - 1) for b in range(a + 1, len(boxes))
        if boxes[a][0] < boxes[b][2] and boxes[b][0] < boxes[a][2]
        and boxes[a][1] < boxes[b][3] and boxes[b][1] < boxes[a][3]
    )
    return out, clashes


# ---------------------------------------------------------------------------
# detached components
# ---------------------------------------------------------------------------

STRAY_ANGLES = 360   # candidate bearings around the main mass
STRAY_STEPS = 44     # bisection depth per bearing


def components(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    adj: dict[int, list[int]] = {i: [] for i in range(n)}
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    seen: set[int] = set()
    out: list[list[int]] = []
    for s in range(n):
        if s in seen:
            continue
        seen.add(s)
        stack, comp = [s], []
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        out.append(sorted(comp))
    return sorted(out, key=len, reverse=True)


def pull_strays(pos, radii, edges: list[tuple[int, int]], gap: float):
    """Dock every component that has no edge into the main one against the main mass.

    The force layout only pulls along edges, so a body nobody links to keeps whatever
    the repulsion pass gave it and ends up adrift at the rim. Each detached component
    is translated rigidly — its own arrangement is already solved — to the closest spot
    that still clears every placed body by `gap`. Bearings are scanned all the way
    round and the smallest displacement wins, so a component docks where it already
    was rather than jumping across the picture.
    """
    pts = [[q[0], q[1]] for q in pos]
    comps = components(len(pts), edges)
    if len(comps) < 2:
        return pts, []

    placed = list(comps[0])
    mx = sum(pts[i][0] for i in placed) / len(placed)
    my = sum(pts[i][1] for i in placed) / len(placed)
    report = []

    def fits(comp, ox, oy) -> bool:
        for i in comp:
            xi, yi, ri = pts[i][0] + ox, pts[i][1] + oy, radii[i]
            for j in placed:
                if math.hypot(pts[j][0] - xi, pts[j][1] - yi) < ri + radii[j] + gap:
                    return False
        return True

    def clearance(comp, ox, oy) -> float:
        """Smallest rim-to-rim distance between this component and the placed mass."""
        return min(
            math.hypot(pts[j][0] - pts[i][0] - ox, pts[j][1] - pts[i][1] - oy)
            - radii[i] - radii[j]
            for i in comp
            for j in placed
        )

    for comp in comps[1:]:
        cx = sum(pts[i][0] for i in comp) / len(comp)
        cy = sum(pts[i][1] for i in comp) / len(comp)
        reach = max(math.hypot(pts[i][0] - cx, pts[i][1] - cy) + radii[i] for i in comp)
        span = max(math.hypot(pts[j][0] - mx, pts[j][1] - my) + radii[j] for j in placed)
        far = span + reach + 4 * gap
        best = None
        for a in range(STRAY_ANGLES):
            th = 2 * math.pi * a / STRAY_ANGLES
            ux, uy = math.cos(th), math.sin(th)
            if not fits(comp, mx + far * ux - cx, my + far * uy - cy):
                continue
            lo, hi = 0.0, far
            for _ in range(STRAY_STEPS):
                mid = (lo + hi) / 2
                if fits(comp, mx + mid * ux - cx, my + mid * uy - cy):
                    hi = mid
                else:
                    lo = mid
            ox, oy = mx + hi * ux - cx, my + hi * uy - cy
            move = math.hypot(ox, oy)
            if best is None or move < best[0]:
                best = (move, ox, oy)
        if best is None:
            report.append({"koerper": comp, "angedockt": False})
            placed.extend(comp)
            continue
        move, ox, oy = best
        before = clearance(comp, 0.0, 0.0)
        after = clearance(comp, ox, oy)
        for i in comp:
            pts[i][0] += ox
            pts[i][1] += oy
        placed.extend(comp)
        report.append({
            "koerper": comp, "angedockt": True, "verschiebung": round(move, 1),
            "abstand_vorher": round(before, 1), "abstand_nachher": round(after, 1),
        })
    return pts, report


HTML = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Die Geburt einer Regulatorik-Galaxie</title>
<style>
  :root { --bg:#0b0e14; --panel:rgba(18,23,33,.86); --line:rgba(255,255,255,.10); --fg:#e8edf6; --dim:#8f9bb0; }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body { background: var(--bg); color: var(--fg); overflow: hidden;
    font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  #stage { position: fixed; inset: 0; }
  canvas { display: block; width: 100%; height: 100%; }
  .panel { position: fixed; background: var(--panel); border: 1px solid var(--line);
    border-radius: 12px; backdrop-filter: blur(8px); }
  #head { top: 14px; left: 14px; padding: 10px 14px; }
  #head h1 { margin: 0 0 1px; font-size: 13px; font-weight: 600; }
  #head .sub { color: var(--dim); font-size: 11px; }
  #clock { margin-top: 5px; font-size: 20px; font-weight: 650; font-variant-numeric: tabular-nums; }
  #counts { color: var(--dim); font-size: 11px; font-variant-numeric: tabular-nums; }
  #legend { top: 14px; right: 14px; padding: 10px 12px; max-width: 306px; }
  #legend h2 { margin: 0 0 8px; font-size: 12px; font-weight: 600; color: var(--dim);
    text-transform: uppercase; letter-spacing: .07em; display: flex; align-items: center; gap: 8px; }
  #legend h2 button { margin-left: auto; padding: 0 7px; font-size: 12px; line-height: 18px; }
  #legend ul { margin: 0; padding: 0; list-style: none; }
  #legend li { display: flex; align-items: center; gap: 7px; padding: 2px 4px; font-size: 11px;
    border-radius: 5px; cursor: pointer; border: 1px solid transparent; }
  #legend li:hover { background: rgba(255,255,255,.07); }
  #legend li.on { background: rgba(255,255,255,.12); border-color: rgba(255,255,255,.28); }
  #legend.off ul, #legend.off .note { display: none; }
  #legend .sw { width: 11px; height: 11px; border-radius: 3px; flex: 0 0 auto; }
  #legend .n { margin-left: auto; color: var(--dim); font-variant-numeric: tabular-nums; }
  #legend .note { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--line);
    color: var(--dim); font-size: 11px; }
  #legend .ring { display:inline-block; width:12px; height:12px; border-radius:50%;
    border:1.4px solid #8f9bb0; background:rgba(143,155,176,.18); vertical-align:-2px; }
  #legend .dash { display:inline-block; width:12px; height:12px; border-radius:50%;
    border:1.4px dashed #8f9bb0; vertical-align:-2px; }
  #legend .sup { display:inline-block; width:12px; height:0; vertical-align:3px;
    border-top:1.6px dashed #B3392F; }
  #legend .note a { color: var(--fg); text-decoration: underline;
    text-underline-offset: 2px; }
  #legend .caveat { color: var(--fg); }
  #bar { left: 14px; right: 14px; bottom: 14px; padding: 8px 12px 6px; }
  #row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  button { background: rgba(255,255,255,.07); color: var(--fg); border: 1px solid var(--line);
    border-radius: 7px; padding: 4px 10px; font: inherit; font-size: 12px; cursor: pointer; }
  button:hover { background: rgba(255,255,255,.13); }
  button.on { background: #2a3a55; border-color: #5b7fa6; }
  #play { min-width: 88px; font-weight: 600; }
  .grp { display: flex; gap: 4px; align-items: center; }
  .grp .lbl { color: var(--dim); font-size: 12px; margin-right: 2px; }
  .spacer { flex: 1 1 auto; }
  #track { position: relative; margin-top: 8px; height: 26px; }
  #scrub { -webkit-appearance: none; appearance: none; position: absolute; inset: 0 0 auto;
    width: 100%; height: 18px; margin: 0; background: transparent; cursor: pointer; z-index: 3; }
  #scrub::-webkit-slider-runnable-track { height: 18px; background: transparent; }
  #scrub::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 18px;
    border-radius: 4px; background: #e8edf6; border: none; box-shadow: 0 0 0 1px rgba(0,0,0,.4); }
  #rail { position: absolute; top: 7px; left: 0; right: 0; height: 4px; border-radius: 2px;
    background: rgba(255,255,255,.12); }
  #fill { position: absolute; top: 7px; left: 0; height: 4px; border-radius: 2px;
    background: linear-gradient(90deg,#B3392F,#F5B301,#1D4ED8); }
  #ticks { position: absolute; top: 16px; left: 0; right: 0; height: 14px; }
  #ticks span { position: absolute; transform: translateX(-50%); color: var(--dim);
    font-size: 10px; font-variant-numeric: tabular-nums; white-space: nowrap; }
  #ticks span::before { content: ""; position: absolute; left: 50%; top: -6px; width: 1px;
    height: 4px; background: rgba(255,255,255,.22); }
  #tip { position: fixed; pointer-events: none; z-index: 9; display: none;
    background: rgba(10,13,20,.95); border: 1px solid var(--line); border-radius: 8px;
    padding: 7px 10px; max-width: 340px; font-size: 12px; line-height: 1.35; }
  #tip .tt { font-weight: 600; }
  #tip .td { color: var(--dim); margin-top: 2px; font-variant-numeric: tabular-nums; }
  /* opening sequence: a text plane running back into a seeded star field */
  #intro { position: fixed; inset: 0; z-index: 20; background: #04060b;
    transition: opacity .8s ease; }
  #intro.gone { opacity: 0; pointer-events: none; }
  #stars { position: absolute; inset: 0; }
  #crawlwrap { position: absolute; inset: 0; overflow: hidden;
    perspective: 320px; perspective-origin: 50% 0%;
    -webkit-mask-image: linear-gradient(to bottom, rgba(0,0,0,0) 0%,
      rgba(0,0,0,.16) 13%, rgba(0,0,0,1) 46%);
    mask-image: linear-gradient(to bottom, rgba(0,0,0,0) 0%,
      rgba(0,0,0,.16) 13%, rgba(0,0,0,1) 46%); }
  #crawl { position: absolute; top: 100%; left: 0; right: 0; margin: 0 auto;
    width: min(80vw, 780px); transform-origin: 50% 0%; transform: rotateX(58deg);
    color: #dce4f2; text-align: justify; text-wrap: pretty; }
  #crawl .eyebrow { margin: 0 0 20px; text-align: center; font-size: 20px; font-weight: 500;
    letter-spacing: .17em; text-transform: uppercase; color: #9fb0cb; }
  #crawl h2 { margin: 0 0 36px; text-align: center; font-size: 52px; line-height: 1.12;
    font-weight: 700; color: #f2f6ff; }
  #crawl p { margin: 0 0 26px; font-size: 27px; line-height: 1.5;
    -webkit-hyphens: auto; hyphens: auto; }
  #crawl .fine { color: #a9b7cd; font-size: 23px; }
  #skip { position: fixed; right: 18px; bottom: 18px; z-index: 21; padding: 7px 14px; }
  @media (max-width: 900px) { #legend { display: none; }
    #crawl h2 { font-size: 34px; } #crawl p { font-size: 20px; }
    #crawl .eyebrow { font-size: 15px; } #crawl .fine { font-size: 17px; } }
</style>
</head>
<body>
<div id="stage"><canvas id="cv"></canvas></div>

<div class="panel" id="head">
  <h1>Die Geburt einer Regulatorik-Galaxie</h1>
  <div class="sub">Verstreute Vorläufer, der Einschlag von DORA, ein System aus
    Rechtsakten — 2006 bis heute</div>
  <div id="clock">—</div>
  <div id="counts">0 Knoten · 0 Kanten</div>
</div>

<div class="panel" id="legend">
  <h2>Quellenhierarchie <button id="legfold" title="Legende ein-/ausklappen">–</button></h2>
  <ul id="legend-list"></ul>
  <div class="note">
    Klick auf eine Zeile hebt diesen Rang hervor, ein zweiter Klick hebt es auf.<br>
    Warm = hohe Verbindlichkeit, kühl = niedrige.<br>
    <span class="ring"></span> Ein Kreis ist ein Rechtsakt; seine Artikel, Anhänge und
    Paragrafen liegen darin.<br>
    <span class="dash"></span> Gestrichelt: Umfang geschätzt — das Dokument liegt nicht
    vollständig im Korpus (Referenzakte hochgerechnet, Standards als Seitenzahl).<br>
    <span class="sup"></span> Rote Strichlinie: von DORA verdrängt — lang gestrichelt
    ganz (aufgehoben), fein gepunktet teilweise (in Kraft, Teilbereich überholt).<br>
    Knotengröße ist indikativ: bei eigenständigen Dokumenten der Textumfang, bei einem
    Rechtsakt die Zahl seiner <em>gespiegelten</em> Einheiten — CRR und CRD sind in
    Wirklichkeit weit umfangreicher als DORA, erscheinen hier aber klein, weil nur wenige
    ihrer Artikel im Korpus liegen. Artikel, Q&As und Aufsichtsseiten sind einheitlich
    klein.<br>
    Zeitpunkt = Erscheinen der ersten Fassung eines Instruments, indikativ eingeordnet;
    die Abfolge stimmt, das einzelne Datum ist kein Beleg. Bestand vor 2006 ab Start
    sichtbar.<br>
    Der Bestand wartet dicht um die Bildmitte; am DORA-Datum schlägt der DORA-Kreis dort
    ein und drückt ihn auf seine Endpositionen nach außen.<br>
    Gezeigt wird der Ausschnitt, der bei der Analyse des Korpus einen Bezug zu DORA
    erkennen ließ: von den 106 Erwägungsgründen nur die 7 verwiesenen, von KWG, CRR und
    CRD nur die einschlägigen Bestimmungen.<br>
    <span class="caveat">Indikative, schematische Darstellung ohne Anspruch auf
    Vollständigkeit — nicht maßstäblich, keine Rechtsberatung.</span>
    Daten, Code und Quellenliste:
    <a href="https://github.com/gnosifex/dora-graph" target="_blank"
       rel="noopener">github.com/gnosifex/dora-graph</a>
  </div>
</div>

<div class="panel" id="bar">
  <div id="row">
    <button id="play">▶ Abspielen</button>
    <button id="restart">↺ Neu</button>
    <div class="grp"><span class="lbl">Tempo</span>
      <button class="sp" data-s="0.5">0,5×</button>
      <button class="sp on" data-s="1">1×</button>
      <button class="sp" data-s="2">2×</button>
      <button class="sp" data-s="4">4×</button>
    </div>
    <div class="spacer"></div>
    <div class="grp"><span class="lbl">Zeitachse</span>
      <button class="md on" data-m="prop">Proportional</button>
      <button class="md" data-m="compact">Kompakt</button>
    </div>
    <div class="grp">
      <button id="sound" title="Erzeugte Klangfläche ein-/ausschalten">♪ Ton</button>
      <button id="intro-again" title="Vorspann erneut abspielen">Vorspann</button>
    </div>
  </div>
  <div id="track">
    <div id="rail"></div><div id="fill"></div>
    <input id="scrub" type="range" min="0" max="1000" value="0" step="1" aria-label="Zeitpunkt">
    <div id="ticks"></div>
  </div>
</div>

<div id="intro">
  <canvas id="stars"></canvas>
  <div id="crawlwrap">
    <div id="crawl">
      <p class="eyebrow">Ein Blick auf die digitale operationale Resilienz</p>
      <h2>Die Geburt einer Regulatorik-Galaxie</h2>
      <p>Lange bevor DORA geschrieben wurde, kreisten die Vorläufer bereits: das
        Kreditwesengesetz, die Mindestanforderungen an das Risikomanagement, die
        bankaufsichtlichen Anforderungen an die IT — dazu ein Gürtel technischer Normen,
        an denen sich die Praxis ausrichtete.</p>
      <p>Im Dezember 2022 schlägt die Verordnung (EU) 2022/2554 in diese Ordnung ein.
        Sie bindet, was verstreut war, verdrängt, was sie ersetzt, und zieht einen Hof
        aus technischen Regulierungsstandards, Leitlinien, Auslegungshilfen und
        Aufsichtsmitteilungen hinter sich her.</p>
      <p>Was nun folgt, ist dieser Vorgang als Zeitraffer: von 2006 bis heute, gefärbt
        nach Verbindlichkeit — warm für bindendes Recht, kühl für unverbindliche
        Auslegung.</p>
      <p class="fine">Die Darstellung ist indikativ und schematisch. Größen und
        Zeitpunkte sind Näherungen, keine Messwerte; gezeigt wird allein der Ausschnitt
        mit Bezug zu DORA. Keine Rechtsberatung.</p>
    </div>
  </div>
  <button id="skip" title="Vorspann überspringen (Esc, Leertaste oder Klick)">Überspringen</button>
</div>

<div id="tip"><div class="tt"></div><div class="td"></div></div>

<script id="graph-data" type="application/json">__DATA__</script>
<script>
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("graph-data").textContent);
  var PALETTE = DATA.palette, COLOR = {}, LABEL = {};
  for (var pi = 0; pi < PALETTE.length; pi++) {
    COLOR[PALETTE[pi][0]] = PALETTE[pi][1];
    LABEL[PALETTE[pi][0]] = PALETTE[pi][2];
  }
  var MONTHS = ["Januar","Februar","März","April","Mai","Juni",
                "Juli","August","September","Oktober","November","Dezember"];
  var DUR = { prop: 45, compact: 30 };
  var FADE = 0.9;

  function toDay(iso) { var p = iso.split("-"); return Date.UTC(+p[0], +p[1] - 1, +p[2]) / 86400000; }
  var T0 = toDay(DATA.t0);

  var nodes = DATA.nodes.map(function (n) {
    var hasPre = n.px !== undefined;
    return {
      t: n.t, d: n.d, g: n.g, cont: !!n.k, cr0: n.cr || 0, cr: n.cr || 0,
      partial: !!n.p, size: n.s || 0, member: (n.c === undefined ? -1 : n.c),
      dv: Math.max(toDay(n.d), T0), realdv: toDay(n.d),
      tx: n.x, ty: n.y, r0: n.r, r: n.r, x: 0, y: 0, vx: 0, vy: 0, sx: 0, sy: 0,
      // the pre-impact seat of the stock, and the label offsets for both layouts
      pre: hasPre, px: (hasPre ? n.px : n.x), py: (hasPre ? n.py : n.y),
      lx: n.lx || 0, ly: n.ly || 0,
      qx: (n.qx === undefined ? (n.lx || 0) : n.qx),
      qy: (n.qy === undefined ? (n.ly || 0) : n.qy),
      lsx: 0, lsy: 0, born: false, a: 0, ap: 0, ac: 0
    };
  });
  var IMP = DATA.impact;
  var edges = DATA.edges, i;

  var dvs = nodes.map(function (n) { return n.dv; });
  var minDV = Math.min.apply(null, dvs), maxDV = Math.max.apply(null, dvs);
  var spanDV = (maxDV - minDV) || 1;
  var events = dvs.slice().sort(function (a, b) { return a - b; })
                  .filter(function (v, k, arr) { return k === 0 || v !== arr[k - 1]; });
  var evIndex = {};
  for (i = 0; i < events.length; i++) evIndex[events[i]] = i;
  var evLast = Math.max(events.length - 1, 1);
  for (i = 0; i < nodes.length; i++) {
    nodes[i].ap = (nodes[i].dv - minDV) / spanDV;
    nodes[i].ac = evIndex[nodes[i].dv] / evLast;
  }

  var mode = "prop", speed = 1, playing = false, tNow = 0, last = 0;
  function duration() { return DUR[mode]; }
  function appearT(n) { return (mode === "prop" ? n.ap : n.ac) * duration(); }
  function progress() { return Math.min(tNow / duration(), 1); }
  function currentDV() {
    var p = progress();
    if (mode === "prop") return minDV + p * spanDV;
    return events[Math.min(Math.round(p * evLast), events.length - 1)];
  }

  // The impact. Everything older than DORA waits packed around the spot DORA lands on
  // and is driven out to its solved seat when the circle arrives; everything younger is
  // born where it belongs. Both are pure functions of the clock, so scrubbing backwards
  // replays the push instead of leaving the picture in a half-pushed state.
  function impactRaw() { return (tNow - appearT(nodes[IMP.k])) / IMP.dur; }
  function impactEase() {
    var u = impactRaw();
    if (u <= 0) return 0;
    if (u >= 1) return 1;
    return 1 - Math.pow(1 - u, 3);
  }

  var cv = document.getElementById("cv"), ctx = cv.getContext("2d");
  var W = 0, H = 0, scale = 1, offX = 0, offY = 0, dpr = 1, rMaxPx = 12, legendOpen = true;
  function place() {
    var e = impactEase(), q, n, tx, ty, lx, ly, o;
    for (q = 0; q < nodes.length; q++) {
      n = nodes[q];
      tx = n.tx; ty = n.ty; lx = n.lx; ly = n.ly;
      if (n.pre && e < 1) {
        tx = n.px + (n.tx - n.px) * e; ty = n.py + (n.ty - n.py) * e;
        lx = n.qx + (n.lx - n.qx) * e; ly = n.qy + (n.ly - n.qy) * e;
      } else if (n.member >= 0) {
        o = nodes[n.member];
        if (o.pre && e < 1) {            // a unit rides inside its own act
          tx = n.tx + (o.px - o.tx) * (1 - e); ty = n.ty + (o.py - o.ty) * (1 - e);
        }
      }
      n.sx = offX + tx * scale; n.sy = offY + ty * scale;
      n.lsx = offX + (tx + lx) * scale; n.lsy = offY + (ty + ly) * scale;
    }
  }
  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // the panels are opaque, so the picture keeps clear of them; folding the legend
    // away hands its column back to the graph
    var padL = 30, padR = (W > 900 && legendOpen) ? 330 : 30, padT = 104, padB = 96;
    var availW = Math.max(W - padL - padR, 120), availH = Math.max(H - padT - padB, 120);
    scale = Math.min(availW / DATA.extent[0], availH / DATA.extent[1]);
    offX = padL + availW / 2; offY = padT + availH / 2;
    rMaxPx = 1;
    for (var q = 0; q < nodes.length; q++) {
      var n = nodes[q];
      n.r = n.r0 * scale; n.cr = n.cr0 * scale;
      if (n.r > rMaxPx) rMaxPx = n.r;
    }
    place();
    for (q = 0; q < nodes.length; q++) {
      if (!nodes[q].born) { nodes[q].x = nodes[q].sx; nodes[q].y = nodes[q].sy; }
    }
  }
  window.addEventListener("resize", resize);

  var CELL = 46;
  function step(dt) {
    var d = Math.min(dt, 0.05), q, n;
    var ease = impactEase();
    place();
    CELL = Math.max(rMaxPx * 2 + 6 * scale, 12);
    var grid = {}, visible = [], free = [];
    for (q = 0; q < nodes.length; q++) {
      n = nodes[q];
      var at = appearT(n);
      if (tNow >= at) {
        if (!n.born) {
          n.born = true;
          var ang = Math.random() * Math.PI * 2, rad = (5 + Math.random() * 8) * scale;
          n.x = n.sx + Math.cos(ang) * rad; n.y = n.sy + Math.sin(ang) * rad;
          n.vx = 0; n.vy = 0;
        }
        n.a = Math.min((tNow - at) / FADE, 1);
        visible.push(n);
        // containers and their members keep their solved positions; only the free
        // nodes get the light settling pass, so nothing can drift out of its circle
        if (!n.cont && n.member < 0) {
          if (n.pre && ease < 1) {       // the push owns the stock until it has landed
            n.x = n.sx; n.y = n.sy; n.vx = 0; n.vy = 0;
          } else {
            free.push(n);
            grid[(Math.floor(n.x / CELL)) + "," + (Math.floor(n.y / CELL))] =
              (grid[(Math.floor(n.x / CELL)) + "," + (Math.floor(n.y / CELL))] || []).concat([n]);
          }
        }
      } else { n.born = false; n.a = 0; }
    }
    for (var v = 0; v < free.length; v++) {
      var a = free[v];
      var gx = Math.floor(a.x / CELL), gy = Math.floor(a.y / CELL);
      for (var ox = -1; ox <= 1; ox++) {
        for (var oy = -1; oy <= 1; oy++) {
          var cell = grid[(gx + ox) + "," + (gy + oy)];
          if (!cell) continue;
          for (var c = 0; c < cell.length; c++) {
            var b = cell[c];
            if (b === a) continue;
            var ex = a.x - b.x, ey = a.y - b.y, dist2 = ex * ex + ey * ey;
            var want = a.r + b.r + 2 * scale;
            if (dist2 < want * want) {
              var dist = Math.sqrt(dist2) || 0.001;
              if (dist2 < 0.0001) { ex = Math.random() - 0.5; ey = Math.random() - 0.5; dist = 0.5; }
              var push = (want - dist) / dist * 90;
              a.vx += ex * push * d; a.vy += ey * push * d;
            }
          }
        }
      }
      a.vx += (a.sx - a.x) * 9 * d; a.vy += (a.sy - a.y) * 9 * d;
      var damp = Math.pow(0.0016, d);
      a.vx *= damp; a.vy *= damp;
      a.x += a.vx * d; a.y += a.vy * d;
    }
    for (v = 0; v < visible.length; v++) {
      n = visible[v];
      if (n.cont || n.member >= 0) { n.x = n.sx; n.y = n.sy; }
    }
    return visible.length;
  }

  var sel = null, clock = 0;
  function gA(g) { return (sel === null || sel === g) ? 1 : 0.11; }

  function draw(visibleCount) {
    ctx.clearRect(0, 0, W, H);
    var q, n, shownEdges = 0;
    var pulse = 0.5 + 0.5 * Math.sin(clock * 4.2), dim = sel === null ? 1 : 0.32;

    // 1) edges, underneath every node and every ring — plain references first, then the
    // supersession lines on top of them
    ctx.lineWidth = 1;
    var supers = [];
    for (q = 0; q < edges.length; q++) {
      var A = nodes[edges[q][0]], B = nodes[edges[q][1]];
      if (!A.born || !B.born) continue;
      var al = Math.min(A.a, B.a);
      if (al <= 0.02) continue;
      shownEdges++;
      al *= Math.max(gA(A.g), gA(B.g)) * dim;
      var kind = edges[q][2] || 0;
      if (kind) { supers.push([A, B, al, kind]); continue; }
      ctx.strokeStyle = "rgba(150,170,205," + (al * 0.22).toFixed(3) + ")";
      ctx.beginPath(); ctx.moveTo(A.x, A.y); ctx.lineTo(B.x, B.y); ctx.stroke();
    }
    for (q = 0; q < supers.length; q++) {
      var S = supers[q], full = S[3] === 1;
      ctx.lineWidth = Math.max(1.2, 1.5 * scale);
      ctx.strokeStyle = "rgba(179,57,47," + (S[2] * (full ? 0.85 : 0.55)).toFixed(3) + ")";
      ctx.setLineDash(full ? [6 * scale, 4 * scale] : [2.5 * scale, 5 * scale]);
      ctx.beginPath(); ctx.moveTo(S[0].x, S[0].y); ctx.lineTo(S[1].x, S[1].y); ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.lineWidth = 1;

    // 2) act containers
    for (q = 0; q < nodes.length; q++) {
      n = nodes[q];
      if (!n.cont || !n.born || n.a <= 0.01) continue;
      var col = COLOR[n.g] || "#8A8F98", ca = n.a * gA(n.g);
      ctx.globalAlpha = ca * 0.13;
      ctx.fillStyle = col;
      ctx.beginPath(); ctx.arc(n.x, n.y, n.cr, 0, 6.2832); ctx.fill();
      ctx.globalAlpha = ca * 0.62;
      ctx.strokeStyle = col;
      ctx.lineWidth = Math.max(1.1, 1.4 * scale);
      if (n.partial) ctx.setLineDash([4.5 * scale, 3.5 * scale]);
      ctx.beginPath(); ctx.arc(n.x, n.y, n.cr, 0, 6.2832); ctx.stroke();
      ctx.setLineDash([]);
      if (sel === n.g) {
        ctx.globalAlpha = 0.25 + 0.45 * pulse;
        ctx.lineWidth = Math.max(1.4, 2.2 * scale);
        ctx.beginPath(); ctx.arc(n.x, n.y, n.cr + 3 + 3 * pulse, 0, 6.2832); ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;

    // 3) the shock wave: DORA lands in the middle of the stock and drives it outward
    var u = impactRaw();
    if (u > 0 && u < 1.6 && nodes[IMP.k].born) {
      var Dn = nodes[IMP.k], f = u / 1.6;
      ctx.globalAlpha = (1 - f) * (1 - f) * 0.55;
      ctx.strokeStyle = COLOR["rang-1"] || "#B3392F";
      ctx.lineWidth = Math.max(1.5, 6 * scale * (1 - f));
      ctx.beginPath();
      ctx.arc(Dn.x, Dn.y, Dn.cr + (IMP.reach - Dn.cr0) * scale * (1 - (1 - f) * (1 - f)),
              0, 6.2832);
      ctx.stroke();
      ctx.globalAlpha = 1; ctx.lineWidth = 1;
    }

    // 4) point nodes
    for (q = 0; q < nodes.length; q++) {
      n = nodes[q];
      if (n.cont || !n.born || n.a <= 0.01) continue;
      var c2 = COLOR[n.g] || "#8A8F98", pa = n.a * gA(n.g);
      if (n.a < 1) {
        ctx.globalAlpha = (1 - n.a) * 0.5;
        ctx.strokeStyle = c2; ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r + (1 - n.a) * 12 * scale, 0, 6.2832); ctx.stroke();
      }
      if (sel === n.g) {                 // a halo, so the 2,5-px ranks can be found at all
        ctx.globalAlpha = 0.2 + 0.5 * pulse;
        ctx.strokeStyle = c2; ctx.lineWidth = 1.6;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r + 3.5 + 3 * pulse, 0, 6.2832); ctx.stroke();
      }
      ctx.globalAlpha = pa;
      if (n.partial) {
        ctx.fillStyle = c2; ctx.globalAlpha = pa * 0.22;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, 6.2832); ctx.fill();
        ctx.globalAlpha = pa;
        ctx.strokeStyle = c2; ctx.lineWidth = Math.max(1.1, 1.5 * scale);
        ctx.setLineDash([3.2 * scale, 2.8 * scale]);
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, 6.2832); ctx.stroke();
        ctx.setLineDash([]);
      } else {
        ctx.fillStyle = c2;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, 6.2832); ctx.fill();
      }
    }
    ctx.globalAlpha = 1;

    // 5) act labels last, seated by the generator so no two of them collide
    ctx.font = "600 " + Math.max(9, Math.min(13, 11 * scale)).toFixed(1) + "px -apple-system, sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    for (q = 0; q < nodes.length; q++) {
      n = nodes[q];
      if (!n.cont || !n.born || n.a <= 0.01) continue;
      ctx.globalAlpha = n.a * 0.94 * gA(n.g);
      ctx.fillStyle = COLOR[n.g] || "#8A8F98";
      ctx.fillText(n.t, n.lsx, n.lsy);
    }
    ctx.globalAlpha = 1;

    var dt2 = new Date(currentDV() * 86400000);
    document.getElementById("clock").textContent =
      MONTHS[dt2.getUTCMonth()] + " " + dt2.getUTCFullYear();
    document.getElementById("counts").textContent =
      visibleCount + " von " + nodes.length + " Knoten · " + shownEdges + " Kanten";
  }

  function frame(ts) {
    var now = ts / 1000, dt = last ? now - last : 0;
    last = now; clock = now;
    if (introActive) introStep(Math.min(dt, 0.1));
    if (playing) {
      tNow += dt * speed;
      if (tNow >= duration()) { tNow = duration(); setPlaying(false); }
      syncScrub();
    }
    audioUpdate();
    draw(step(dt));
    requestAnimationFrame(frame);
  }

  var scrub = document.getElementById("scrub");
  var fill = document.getElementById("fill");
  var playBtn = document.getElementById("play");
  function syncScrub() {
    var p = progress();
    scrub.value = String(Math.round(p * 1000));
    fill.style.width = (p * 100).toFixed(2) + "%";
  }
  function setPlaying(on) { playing = on; playBtn.textContent = on ? "❚❚ Pause" : "▶ Abspielen"; }
  playBtn.addEventListener("click", function () {
    if (!playing && tNow >= duration()) tNow = 0;
    setPlaying(!playing);
  });
  document.getElementById("restart").addEventListener("click", function () {
    tNow = 0; syncScrub(); setPlaying(true);
  });
  scrub.addEventListener("input", function () {
    tNow = (+scrub.value / 1000) * duration();
    fill.style.width = (+scrub.value / 10).toFixed(2) + "%";
  });
  var spBtns = document.querySelectorAll(".sp");
  for (i = 0; i < spBtns.length; i++) {
    spBtns[i].addEventListener("click", function (ev) {
      speed = parseFloat(ev.currentTarget.getAttribute("data-s"));
      for (var b = 0; b < spBtns.length; b++) spBtns[b].classList.remove("on");
      ev.currentTarget.classList.add("on");
    });
  }
  var mdBtns = document.querySelectorAll(".md");
  for (i = 0; i < mdBtns.length; i++) {
    mdBtns[i].addEventListener("click", function (ev) {
      var p = progress();
      mode = ev.currentTarget.getAttribute("data-m");
      for (var b = 0; b < mdBtns.length; b++) mdBtns[b].classList.remove("on");
      ev.currentTarget.classList.add("on");
      tNow = p * duration();
      buildTicks(); syncScrub();
    });
  }
  document.addEventListener("keydown", function (ev) {
    if (introActive && (ev.code === "Space" || ev.code === "Escape" || ev.key === "Escape")) {
      ev.preventDefault(); finishIntro(); return;
    }
    if (ev.code === "Space") { ev.preventDefault(); playBtn.click(); }
  });

  function fractionFor(dv) {
    if (mode === "prop") return (dv - minDV) / spanDV;
    var lo = 0, hi = events.length - 1, mid;
    while (lo < hi) { mid = (lo + hi) >> 1; if (events[mid] < dv) lo = mid + 1; else hi = mid; }
    return lo / evLast;
  }
  function buildTicks() {
    var host = document.getElementById("ticks");
    host.innerHTML = "";
    var y0 = new Date(minDV * 86400000).getUTCFullYear();
    var y1 = new Date(maxDV * 86400000).getUTCFullYear();
    var placed = -99;
    for (var y = y0; y <= y1; y++) {
      var f = fractionFor(Date.UTC(y, 0, 1) / 86400000);
      if (f < 0 || f > 1) continue;
      if (f * 100 - placed < 3.6) continue;
      placed = f * 100;
      var s = document.createElement("span");
      s.textContent = String(y);
      s.style.left = (f * 100).toFixed(2) + "%";
      host.appendChild(s);
    }
  }

  var legendRows = [];
  (function () {
    var counts = {};
    for (var q = 0; q < nodes.length; q++) counts[nodes[q].g] = (counts[nodes[q].g] || 0) + 1;
    var ul = document.getElementById("legend-list");
    function pick(key) {
      return function () {
        sel = (sel === key) ? null : key;
        for (var b = 0; b < legendRows.length; b++) {
          legendRows[b][0].className = (sel === legendRows[b][1]) ? "on" : "";
        }
      };
    }
    for (var p = 0; p < PALETTE.length; p++) {
      var li = document.createElement("li");
      var sw = document.createElement("span");
      sw.className = "sw"; sw.style.background = PALETTE[p][1];
      var tx = document.createElement("span"); tx.textContent = PALETTE[p][2];
      var nn = document.createElement("span");
      nn.className = "n"; nn.textContent = counts[PALETTE[p][0]] || 0;
      li.appendChild(sw); li.appendChild(tx); li.appendChild(nn);
      li.title = "Diesen Rang hervorheben";
      li.addEventListener("click", pick(PALETTE[p][0]));
      legendRows.push([li, PALETTE[p][0]]);
      ul.appendChild(li);
    }
    var legend = document.getElementById("legend"), fold = document.getElementById("legfold");
    fold.addEventListener("click", function () {
      legendOpen = !legendOpen;
      legend.className = legendOpen ? "panel" : "panel off";
      fold.textContent = legendOpen ? "–" : "+";
      resize();
    });
  })();

  var tip = document.getElementById("tip");
  var tipT = tip.querySelector(".tt"), tipD = tip.querySelector(".td");
  cv.addEventListener("mousemove", function (ev) {
    var rect = cv.getBoundingClientRect();
    var mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    var best = null, bd = 1e9, q, n, ex, ey, d2;
    for (q = 0; q < nodes.length; q++) {          // points first
      n = nodes[q];
      if (n.cont || !n.born || n.a < 0.3) continue;
      ex = n.x - mx; ey = n.y - my; d2 = ex * ex + ey * ey;
      var lim = (n.r + 6) * (n.r + 6);
      if (d2 < lim && d2 < bd) { bd = d2; best = n; }
    }
    if (!best) {                                   // then container rings
      for (q = 0; q < nodes.length; q++) {
        n = nodes[q];
        if (!n.cont || !n.born || n.a < 0.3) continue;
        var dd = Math.abs(Math.sqrt((n.x - mx) * (n.x - mx) + (n.y - my) * (n.y - my)) - n.cr);
        if (dd < 8 && dd < bd) { bd = dd; best = n; }
      }
    }
    if (best) {
      tipT.textContent = best.t;
      tipD.textContent = best.d + " · " + (LABEL[best.g] || best.g)
        + (best.cont ? " · Rechtsakt" : "");
      tip.style.display = "block";
      var tw = tip.offsetWidth, th = tip.offsetHeight;
      tip.style.left = Math.min(ev.clientX + 14, window.innerWidth - tw - 10) + "px";
      tip.style.top = Math.max(ev.clientY - th - 12, 8) + "px";
    } else { tip.style.display = "none"; }
  });
  cv.addEventListener("mouseleave", function () { tip.style.display = "none"; });

  // -------------------------------------------------------------------------
  // Opening sequence. A text plane tilted away from the viewer travels toward the
  // vanishing point over a star field; both are drawn here, nothing is loaded. The
  // clock is the same rAF loop the graph runs on, so skipping is just a state change.
  // -------------------------------------------------------------------------
  var IKEY = "dora-graph.intro", SKEY = "dora-graph.sound";
  var INTRO_DUR = 36;
  var reduce = false;
  try { reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e0) {}

  var intro = document.getElementById("intro");
  var crawl = document.getElementById("crawl");
  var stars = document.getElementById("stars");
  var skipBtn = document.getElementById("skip");
  var soundBtn = document.getElementById("sound");
  var introBtn = document.getElementById("intro-again");
  var introActive = false, introT = 0, introDist = 900, introLead = 160, hideTimer = 0;

  function store(k, v) { try { localStorage.setItem(k, v); } catch (e1) {} }
  function stored(k) { try { return localStorage.getItem(k); } catch (e2) { return null; } }

  // A seeded generator: the star field is a fixed picture, the same on every visit,
  // and the noise bed below is the same buffer every time it is built.
  function seeded(a) {
    return function () {
      a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function drawStars() {
    var w = stars.clientWidth, h = stars.clientHeight;
    if (!w || !h) return;
    var dp = Math.min(window.devicePixelRatio || 1, 2);
    stars.width = Math.round(w * dp); stars.height = Math.round(h * dp);
    var sc = stars.getContext("2d");
    sc.setTransform(dp, 0, 0, dp, 0, 0);
    sc.clearRect(0, 0, w, h);
    var rnd = seeded(20260819), count = Math.round(w * h * 0.00019);
    for (var s = 0; s < count; s++) {
      var x = rnd() * w, y = rnd() * h;
      var r = 0.35 + rnd() * rnd() * 1.4, a = 0.16 + rnd() * 0.6;
      sc.globalAlpha = a;
      sc.fillStyle = (s % 19 === 0) ? "#cfe0ff" : "#ffffff";
      sc.beginPath(); sc.arc(x, y, r, 0, 6.2832); sc.fill();
    }
    sc.globalAlpha = 1;
  }

  function introLayout() {
    // The plane is hinged at the bottom edge of the screen and tilted away, so the
    // travel is measured in its own tilted coordinates: a lead-in that holds the first
    // line just out of sight, then its whole length, then far enough past the hinge for
    // the last line to have shrunk into the masked band at the top.
    introLead = window.innerHeight * 0.2;
    introDist = introLead + crawl.offsetHeight + window.innerHeight * 1.25;
  }
  function introPlace(p) {
    crawl.style.transform = "rotateX(58deg) translateY("
      + (introLead - introDist * p).toFixed(1) + "px)";
  }
  function introStep(dt) {
    introT += dt;
    var p = introT / INTRO_DUR;
    if (p >= 1) { introPlace(1); finishIntro(); return; }
    introPlace(p);
  }
  function startIntro() {
    if (hideTimer) { clearTimeout(hideTimer); hideTimer = 0; }
    intro.style.display = "block";
    intro.className = "";
    introT = 0; introActive = true;
    setPlaying(false); tNow = 0; syncScrub();
    drawStars(); introLayout(); introPlace(0);
  }
  function finishIntro() {
    if (!introActive) return;
    introActive = false;
    store(IKEY, "1");
    intro.className = "gone";
    hideTimer = setTimeout(function () { intro.style.display = "none"; hideTimer = 0; }, 900);
    tNow = 0; syncScrub(); setPlaying(true);
  }
  intro.addEventListener("click", function () { finishIntro(); });
  skipBtn.addEventListener("click", function (ev) { ev.stopPropagation(); finishIntro(); });
  introBtn.addEventListener("click", function () { startIntro(); });
  window.addEventListener("resize", function () {
    drawStars();
    introLayout();
    if (introActive) introPlace(Math.min(introT / INTRO_DUR, 1));
  });

  // -------------------------------------------------------------------------
  // Sound. Off until the user asks for it, generated in the browser and never loaded:
  // three low oscillators a hair apart beat against each other, a slow filter breathes
  // over them, a filtered noise bed sits underneath. No pitch ever changes, so there is
  // nothing to follow — it is a surface, not a piece of music. The picture only moves
  // the level and the filter: quiet under the opening, a swell where DORA lands, and a
  // slow retreat as the timeline runs out.
  // -------------------------------------------------------------------------
  var soundOn = false, actx = null, master = null, lp = null;
  var lastLevel = -1, lastCut = -1;
  var MASTER_MAX = 0.16;

  function buildAudio() {
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return false;
    try { actx = new AC(); } catch (e3) { return false; }
    master = actx.createGain();
    master.gain.value = 0.0001;
    master.connect(actx.destination);
    lp = actx.createBiquadFilter();
    lp.type = "lowpass"; lp.frequency.value = 240; lp.Q.value = 0.7;
    lp.connect(master);
    var fs = [61.7, 62.13, 92.9], k, o, g;
    for (k = 0; k < fs.length; k++) {
      o = actx.createOscillator();
      o.type = (k === 2) ? "triangle" : "sine";
      o.frequency.value = fs[k];
      g = actx.createGain();
      g.gain.value = (k === 2) ? 0.16 : 0.34;
      o.connect(g); g.connect(lp); o.start();
    }
    var lfo = actx.createOscillator();
    lfo.type = "sine"; lfo.frequency.value = 0.031;
    var amt = actx.createGain(); amt.gain.value = 150;
    lfo.connect(amt); amt.connect(lp.frequency); lfo.start();
    var len = Math.floor(actx.sampleRate * 4);
    var buf = actx.createBuffer(1, len, actx.sampleRate);
    var ch = buf.getChannelData(0), rnd = seeded(1774), prev = 0, s;
    for (s = 0; s < len; s++) {
      prev = prev * 0.94 + (rnd() * 2 - 1) * 0.06;
      ch[s] = prev * 3;
    }
    var src = actx.createBufferSource();
    src.buffer = buf; src.loop = true;
    var bp = actx.createBiquadFilter();
    bp.type = "bandpass"; bp.frequency.value = 430; bp.Q.value = 0.6;
    var ng = actx.createGain(); ng.gain.value = 0.05;
    src.connect(bp); bp.connect(ng); ng.connect(master); src.start();
    return true;
  }

  function audioUpdate() {
    if (!soundOn || !actx || actx.state !== "running") return;
    var lvl = introActive ? 0.34 : 0.62, cut = 240, p = progress();
    if (!introActive) {
      var u = impactRaw();
      if (u > 0 && u < 2.2) {
        var b = Math.sin(Math.PI * (u * 0.4545));
        lvl += 0.38 * b; cut += 900 * b;
      }
      if (p > 0.94) {
        var f = (1 - p) * 16.6667;
        lvl *= 0.25 + 0.75 * f; cut = 150 + (cut - 150) * f;
      }
    }
    if (Math.abs(lvl - lastLevel) > 0.004) {
      lastLevel = lvl;
      master.gain.setTargetAtTime(Math.max(lvl * MASTER_MAX, 0.0001), actx.currentTime, 0.35);
    }
    if (Math.abs(cut - lastCut) > 6) {
      lastCut = cut;
      lp.frequency.setTargetAtTime(cut, actx.currentTime, 0.35);
    }
  }

  function setSound(on) {
    if (on && !actx && !buildAudio()) return;
    soundOn = on;
    soundBtn.className = on ? "on" : "";
    store(SKEY, on ? "1" : "0");
    lastLevel = -1; lastCut = -1;
    if (!actx) return;
    if (on) {
      if (actx.resume) actx.resume();
    } else {
      master.gain.setTargetAtTime(0.0001, actx.currentTime, 0.25);
      setTimeout(function () { if (!soundOn && actx && actx.suspend) actx.suspend(); }, 1400);
    }
  }
  soundBtn.addEventListener("click", function () { setSound(!soundOn); });
  if (reduce) { soundBtn.disabled = true; soundBtn.title = "Bei reduzierter Bewegung aus"; }

  resize(); buildTicks(); syncScrub();
  if (stored(IKEY) === "1" || reduce) {
    intro.style.display = "none";
    setPlaying(true);
  } else {
    startIntro();
  }
  // A remembered "on" still waits for a gesture — browsers do not allow sound before one.
  if (!reduce && stored(SKEY) === "1") {
    var arm = function () {
      document.removeEventListener("pointerdown", arm);
      document.removeEventListener("keydown", arm);
      setSound(true);
    };
    document.addEventListener("pointerdown", arm);
    document.addEventListener("keydown", arm);
  }
  requestAnimationFrame(frame);
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# the static preview image
# ---------------------------------------------------------------------------

# docs/preview.svg is the end frame of the timelapse frozen into a file: every node
# visible, no clock, nothing that moves. It is written from the very payload the page
# embeds, so the preview cannot drift away from the site, and it is drawn with
# presentation attributes only — GitHub sanitises SVG before it renders a README image,
# so a <style> block, a webfont or any remote reference would be dropped or would never
# load. Every colour is a literal, the ground is painted rather than left transparent,
# and each text element carries its own font, size and fill.
# The working frame is deliberately roomy: the picture is fitted inside it and the file
# is then cropped to what was actually drawn, so no constant here fixes the finished
# proportions — the content does.
SVG_W, SVG_H = 1600.0, 1180.0
SVG_MARGIN = 16.0                    # clear space between the frame and anything drawn
SVG_CROP = 14.0                      # the narrow border the finished viewBox keeps
SVG_BG = "#0b0e14"
SVG_FG, SVG_DIM = "#e8edf6", "#8f9bb0"
SVG_PANEL, SVG_PANEL_A = "#121721", "0.9"
SVG_BORDER, SVG_BORDER_A = "#ffffff", "0.12"
SVG_EDGE = "#96aacd"                 # the page's rgba(150,170,205,.22)
SVG_SUPER = "#b3392f"                # the page's rgba(179,57,47,…)
SVG_FONT = ("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, "
            "Arial, sans-serif")
SVG_LEGEND_W = 330.0

# Label seating for the still. The page can let a label graze a dot — the dot moves, and
# the reader can hover it; a frozen frame cannot, so the preview seats the act labels
# itself: clear of every other label, of every circle (its own ring included) and of the
# two panels, with a dark outline carrying the text over the edges underneath.
LBL_RING_GAP = 5.0                   # from the ring the label belongs to
LBL_LABEL_PAD = 3.5                  # between two labels
LBL_NODE_PAD = 2.5                   # from any circle the label is not attached to
LBL_PANEL_PAD = 7.0
LBL_HALO = 3.4
LBL_DIRS = ((0.0, -1.0), (0.0, 1.0), (-1.0, 0.0), (1.0, 0.0),
            (-0.75, -0.75), (0.75, -0.75), (-0.75, 0.75), (0.75, 0.75),
            (-0.45, -1.0), (0.45, -1.0), (-0.45, 1.0), (0.45, 1.0))
LBL_ABOVE_BONUS = 0.86               # how much the reading position is worth
LBL_RINGS = 22                       # how far out a crowded label may be pushed
LBL_STEP_X, LBL_STEP_Y = 5.0, 5.5
LBL_LEADER = 15.0                    # beyond this gap a label is tied back to its ring

SVG_TITLE = "Die Geburt einer Regulatorik-Galaxie"
SVG_SUB = ("DORA, seine Vorläufer und sein Folgerecht — indikative, schematische "
           "Darstellung")
SVG_LEGEND_HEAD = "Quellenhierarchie"
SVG_NOTES = (
    "Warm = hohe Verbindlichkeit, kühl = niedrige.",
    "Ein Kreis ist ein Rechtsakt; die Punkte darin sind seine Artikel, Anhänge "
    "und Paragrafen.",
    "Gestrichelter Rand: Umfang geschätzt. Rote Linie: von DORA verdrängt — "
    "gestrichelt ganz, gepunktet teilweise.",
    "Größen und Zeitpunkte sind Näherungen, keine Messwerte. Keine Rechtsberatung.",
    "github.com/gnosifex/dora-graph",
)

# Advance widths as a share of the font size, by character class. The page can ask the
# canvas how wide a string is; a file cannot, so the wrapper here and the reader in
# check_site.py both work off this table. It only has to be consistent and a little
# generous — never exact.
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


def wrap_text(text: str, fs: float, width: float) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split(" "):
        trial = word if not line else line + " " + word
        if line and text_width(trial, fs) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def relative_luminance(colour: str) -> float:
    def channel(v: int) -> float:
        f = v / 255.0
        return f / 12.92 if f <= 0.04045 else ((f + 0.055) / 1.055) ** 2.4
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    a, b = relative_luminance(fg), relative_luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def svg_num(v: float) -> str:
    """One decimal, no trailing zero, no negative zero — so two builds agree byte for
    byte and the file stays small."""
    s = f"{v:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
    return "0" if s == "-0" else s


def svg_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def svg_text(x: float, y: float, text: str, fs: float, fill: str, *,
             weight: str = "400", anchor: str = "start", halo: float = 0.0) -> str:
    """One text element carrying its whole style — no class, no inheritance, nothing a
    sanitiser could strip on the way to a README. `halo` widens it into the backing copy
    that a second, unstroked element is then drawn over."""
    ring = (f' stroke="{fill}" stroke-width="{svg_num(halo)}" stroke-linejoin="round"'
            if halo else "")
    return (f'<text x="{svg_num(x)}" y="{svg_num(y)}" font-family="{SVG_FONT}" '
            f'font-size="{svg_num(fs)}" font-weight="{weight}" fill="{fill}"{ring} '
            f'text-anchor="{anchor}">{svg_escape(text)}</text>')


def svg_panel(x: float, y: float, w: float, h: float) -> str:
    return (f'<rect x="{svg_num(x)}" y="{svg_num(y)}" width="{svg_num(w)}" '
            f'height="{svg_num(h)}" rx="12" fill="{SVG_PANEL}" '
            f'fill-opacity="{SVG_PANEL_A}" stroke="{SVG_BORDER}" '
            f'stroke-opacity="{SVG_BORDER_A}" stroke-width="1"/>')


def boxes_overlap(a, b, pad: float = 0.0) -> bool:
    return (a[0] < b[2] + pad and b[0] < a[2] + pad
            and a[1] < b[3] + pad and b[1] < a[3] + pad)


def box_hits_circle(box, cx: float, cy: float, r: float, pad: float = 0.0) -> bool:
    nx = min(max(cx, box[0]), box[2])
    ny = min(max(cy, box[1]), box[3])
    return math.hypot(cx - nx, cy - ny) < r + pad


def fit_graph(circles, seats, panels, frame) -> tuple[float, float, float]:
    """Largest scale at which the whole picture clears the panels, and where to put it.

    The graph is a blob inside a rectangular extent, so the extent's corners carry no
    ink: a panel may reach well into it as long as it meets nothing. Fitting the graph
    into the leftover rectangle instead would give away that room, so the scale is
    bisected against the real objects — every circle and every label seat — and the
    placement closest to the middle of what is still free wins, which keeps the picture
    centred rather than hugging whichever edge happened to admit it first.
    """
    fx0, fy0, fx1, fy1 = frame

    def offsets(s: float, steps: int):
        span_x = (fx1 - fx0) - s * (max(c[0] + c[2] for c in circles)
                                    - min(c[0] - c[2] for c in circles))
        span_y = (fy1 - fy0) - s * (max(c[1] + c[2] for c in circles)
                                    - min(c[1] - c[2] for c in circles))
        if span_x < 0 or span_y < 0:
            return []
        base_x = fx0 - s * min(c[0] - c[2] for c in circles)
        base_y = fy0 - s * min(c[1] - c[2] for c in circles)
        return [(base_x + span_x * i / steps, base_y + span_y * j / steps)
                for i in range(steps + 1) for j in range(steps + 1)]

    def clear(s: float, ox: float, oy: float) -> bool:
        for p in panels:
            for cx, cy, r in circles:
                if box_hits_circle(p, ox + cx * s, oy + cy * s, r * s):
                    return False
            for x0, y0, x1, y1 in seats:
                if boxes_overlap(p, (ox + x0 * s, oy + y0 * s, ox + x1 * s, oy + y1 * s)):
                    return False
        return True

    lo, hi = 0.4, 4.0
    for _ in range(22):
        mid = (lo + hi) / 2
        if any(clear(mid, ox, oy) for ox, oy in offsets(mid, 16)):
            lo = mid
        else:
            hi = mid
    good = [(ox, oy) for ox, oy in offsets(lo, 30) if clear(lo, ox, oy)]
    if not good:                      # only reachable if the frame itself is too small
        return lo, fx0, fy0
    mx = sum(o[0] for o in good) / len(good)
    my = sum(o[1] for o in good) / len(good)
    ox, oy = min(good, key=lambda o: (o[0] - mx) ** 2 + (o[1] - my) ** 2)
    return lo, ox, oy


def seat_labels(spots, texts, order, circles, panels, frame, fs):
    """Put every act label at the nearest free spot around its own ring.

    Just above the circle is the reading position, and the biggest act picks first so the
    strongest ring keeps it. Everything else takes the closest place that is free of the
    labels already seated, of every circle and of the panels — nearest wins rather than
    first-direction-that-fits, because a label that drifts far from its circle stops
    naming it.
    """
    placed: dict[int, tuple[float, float, tuple]] = {}
    for k in order:
        cx, cy, r = spots[k]
        w = text_width(texts[k], fs)
        h = fs * 1.24
        best = None
        for ring in range(LBL_RINGS):
            for dx, dy in LBL_DIRS:
                lx = cx + dx * (r + LBL_RING_GAP + w / 2 + ring * LBL_STEP_X)
                ly = cy + dy * (r + LBL_RING_GAP + h / 2 + ring * LBL_STEP_Y)
                cost = math.hypot(lx - cx, ly - cy) * (LBL_ABOVE_BONUS if dx == 0 and dy < 0
                                                       else 1.0)
                if best is not None and cost >= best[0]:
                    continue
                box = (lx - w / 2, ly - h / 2, lx + w / 2, ly + h / 2)
                if (box[0] < frame[0] or box[1] < frame[1]
                        or box[2] > frame[2] or box[3] > frame[3]):
                    continue
                if any(boxes_overlap(box, o[2], LBL_LABEL_PAD) for o in placed.values()):
                    continue
                if any(boxes_overlap(box, p, LBL_PANEL_PAD) for p in panels):
                    continue
                if any(box_hits_circle(box, *c, LBL_NODE_PAD) for c in circles):
                    continue
                best = (cost, lx, ly, box)
        if best is None:              # never seen; kept so a hard case still draws
            ly = cy - (r + LBL_RING_GAP + h / 2 + LBL_RINGS * LBL_STEP_Y)
            best = (0.0, cx, ly, (cx - w / 2, ly - h / 2, cx + w / 2, ly + h / 2))
        placed[k] = best[1:]
    return placed


def render_preview(payload: dict) -> tuple[str, dict]:
    """Draw the solved picture as a standalone SVG and report what went into it.

    Geometry, palette and z-order follow the canvas renderer exactly — edges first,
    then the act circles, then the dots, then the labels — so the file reads as the
    page's last frame rather than as a second, differently-shaped drawing.
    """
    nodes, edges = payload["nodes"], payload["edges"]
    colour = {p[0]: p[1] for p in payload["palette"]}
    ext_w, ext_h = payload["extent"]

    # --- the two panels, measured before anything is placed: their boxes are what the
    # picture has to fit around
    t_fs, s_fs, t_pad = 30.0, 16.0, 16.0
    t_w = 2 * t_pad + max(text_width(SVG_TITLE, t_fs), text_width(SVG_SUB, s_fs))
    t_h = 2 * t_pad + t_fs * 1.06 + 6.0 + s_fs * 1.2
    title_box = (SVG_MARGIN, SVG_MARGIN, SVG_MARGIN + t_w, SVG_MARGIN + t_h)

    l_pad, sw, gap = 16.0, 15.0, 10.0
    row_fs, note_fs, head_fs, lead = 14.5, 13.0, 14.0, 18.0
    row_w = SVG_LEGEND_W - 2 * l_pad - sw - gap
    note_w = SVG_LEGEND_W - 2 * l_pad
    rows = [(p[1], wrap_text(p[2], row_fs, row_w)) for p in payload["palette"]]
    notes = [wrap_text(t, note_fs, note_w) for t in SVG_NOTES]
    # heading + rank rows + the divider block + the notes; the last note's trailing gap
    # is eaten by the bottom padding, hence the -5
    l_h = (l_pad + head_fs * 1.5 + 8.0
           + sum(lead * len(t) + 6.0 for _, t in rows)
           + 12.0 + sum(lead * len(t) + 5.0 for t in notes) + l_pad - 5.0)
    l_x = SVG_W - SVG_MARGIN - SVG_LEGEND_W
    legend_box = (l_x, SVG_MARGIN, l_x + SVG_LEGEND_W, SVG_MARGIN + l_h)
    panels = (title_box, legend_box)
    frame = (SVG_MARGIN, SVG_MARGIN, SVG_W - SVG_MARGIN, SVG_H - SVG_MARGIN)

    # --- fit the picture around the panels rather than beside them
    graph_circles = [(n["x"], n["y"], n["cr"] if n.get("k") else n["r"]) for n in nodes]
    seats = []
    for n in nodes:
        if not n.get("k"):
            continue
        # the seat place_labels reserved, in design units — scale free, so the fit can
        # weigh it without knowing the answer yet
        w, h = text_width(n["t"], LABEL_FS), LABEL_FS * 1.24
        seats.append((n["x"] + n["lx"] - w / 2, n["y"] + n["ly"] - h / 2,
                      n["x"] + n["lx"] + w / 2, n["y"] + n["ly"] + h / 2))
    scale, off_x, off_y = fit_graph(graph_circles, seats, panels, frame)

    def at(n: dict) -> tuple[float, float]:
        return off_x + n["x"] * scale, off_y + n["y"] * scale

    # --- 1) edges: three collected paths instead of 590 elements
    plain: list[str] = []
    sup_full: list[str] = []
    sup_part: list[str] = []
    for e in edges:
        ax, ay = at(nodes[e[0]])
        bx, by = at(nodes[e[1]])
        seg = f"M{svg_num(ax)} {svg_num(ay)}L{svg_num(bx)} {svg_num(by)}"
        kind = e[2] if len(e) > 2 else 0
        (sup_full if kind == 1 else sup_part if kind == 2 else plain).append(seg)
    sup_w = svg_num(max(1.2, 1.5 * scale))
    edge_parts = [
        f'<path d="{"".join(plain)}" fill="none" stroke="{SVG_EDGE}" '
        f'stroke-opacity="0.22" stroke-width="1"/>'
    ]
    for segs, op, dash in ((sup_full, "0.85", (6.0, 4.0)), (sup_part, "0.55", (2.5, 5.0))):
        if not segs:
            continue
        edge_parts.append(
            f'<path d="{"".join(segs)}" fill="none" stroke="{SVG_SUPER}" '
            f'stroke-opacity="{op}" stroke-width="{sup_w}" stroke-linecap="butt" '
            f'stroke-dasharray="{svg_num(dash[0] * scale)} {svg_num(dash[1] * scale)}"/>')

    # --- 2) act circles, 3) dots — one circle element per node, so the file can be
    # counted against the graph without knowing anything about the layout
    ring_w = svg_num(max(1.1, 1.4 * scale))
    dot_w = svg_num(max(1.1, 1.5 * scale))
    cont_dash = f'{svg_num(4.5 * scale)} {svg_num(3.5 * scale)}'
    dot_dash = f'{svg_num(3.2 * scale)} {svg_num(2.8 * scale)}'
    containers: list[str] = []
    dots: list[str] = []
    for n in nodes:
        cx, cy = at(n)
        col = colour.get(n["g"], "#8a8f98")
        head = f'<circle cx="{svg_num(cx)}" cy="{svg_num(cy)}"'
        if n.get("k"):
            dash = f' stroke-dasharray="{cont_dash}"' if n.get("p") else ""
            containers.append(
                f'{head} r="{svg_num(n["cr"] * scale)}" fill="{col}" fill-opacity="0.13" '
                f'stroke="{col}" stroke-opacity="0.62" stroke-width="{ring_w}"{dash}/>')
        elif n.get("p"):
            dots.append(
                f'{head} r="{svg_num(n["r"] * scale)}" fill="{col}" fill-opacity="0.22" '
                f'stroke="{col}" stroke-width="{dot_w}" stroke-dasharray="{dot_dash}"/>')
        else:
            dots.append(f'{head} r="{svg_num(n["r"] * scale)}" fill="{col}"/>')

    # --- 4) act labels: seated here, not on the page's offsets. The page fades them in
    # to 0,94 alpha and clamps the size at 13 px; a still has no fade and is read at half
    # size in a README, so both give way to legibility.
    label_fs = LABEL_FS * scale
    spots = {i: (*at(n), n["cr"] * scale) for i, n in enumerate(nodes) if n.get("k")}
    texts = {i: nodes[i]["t"] for i in spots}
    obstacles = [(off_x + x * scale, off_y + y * scale, r * scale)
                 for x, y, r in graph_circles]
    seated = seat_labels(spots, texts, sorted(spots, key=lambda i: -spots[i][2]),
                         obstacles, panels, frame, label_fs)
    labels: list[str] = []
    halos: list[str] = []
    leaders: list[str] = []
    for i, (lx, ly, box) in sorted(seated.items()):
        base = ly + label_fs * 0.35
        col = colour.get(nodes[i]["g"], "#8a8f98")
        # the halo is its own element rather than paint-order: a renderer that does not
        # honour the property would otherwise paint the outline over the glyph
        halos.append(svg_text(lx, base, texts[i], label_fs, SVG_BG, weight="600",
                              anchor="middle", halo=LBL_HALO))
        labels.append(svg_text(lx, base, texts[i], label_fs, col,
                               weight="600", anchor="middle"))
        # A wide name on a small ring cannot always sit beside it. Where the free spot
        # is far enough that the label would start naming its neighbours instead, a hair
        # line ties it back to the circle it belongs to.
        cx, cy, r = spots[i]
        nx = min(max(cx, box[0]), box[2])
        ny = min(max(cy, box[1]), box[3])
        d = math.hypot(nx - cx, ny - cy)
        if d - r <= max(LBL_LEADER, 0.5 * r) or d < 1e-6:
            continue
        ux, uy = (nx - cx) / d, (ny - cy) / d
        leaders.append(
            f'<path d="M{svg_num(cx + ux * (r + 2))} {svg_num(cy + uy * (r + 2))}'
            f'L{svg_num(nx - ux * 2)} {svg_num(ny - uy * 2)}" fill="none" stroke="{col}" '
            f'stroke-opacity="0.5" stroke-width="1.2"/>')

    # --- the title panel, top left
    chrome = [svg_panel(*title_box[:2], t_w, t_h),
              svg_text(SVG_MARGIN + t_pad, SVG_MARGIN + t_pad + t_fs * 0.82,
                       SVG_TITLE, t_fs, SVG_FG, weight="700"),
              svg_text(SVG_MARGIN + t_pad, SVG_MARGIN + t_pad + t_fs * 1.06 + 6.0 + s_fs * 0.9,
                       SVG_SUB, s_fs, SVG_DIM)]

    # --- the legend, right margin: a swatch per rank, then the reading notes. A README
    # shows the file at roughly half its nominal width, so this is set larger than the
    # page's 11 px — the ranks are the one thing a still has to carry on its own.
    chrome.append(svg_panel(l_x, SVG_MARGIN, SVG_LEGEND_W, l_h))
    y = SVG_MARGIN + l_pad + head_fs * 0.85
    chrome.append(svg_text(l_x + l_pad, y, SVG_LEGEND_HEAD, head_fs, SVG_DIM, weight="600"))
    y += head_fs * 0.7 + 8.0
    for col, lines in rows:
        chrome.append(
            f'<rect x="{svg_num(l_x + l_pad)}" y="{svg_num(y + 1.0)}" '
            f'width="{svg_num(sw)}" height="{svg_num(sw)}" rx="3.5" fill="{col}"/>')
        for k, line in enumerate(lines):
            chrome.append(svg_text(l_x + l_pad + sw + gap, y + row_fs * 0.82 + k * lead,
                                   line, row_fs, SVG_FG))
        y += lead * len(lines) + 6.0
    y += 6.0
    chrome.append(
        f'<path d="M{svg_num(l_x + l_pad)} {svg_num(y)}H{svg_num(l_x + SVG_LEGEND_W - l_pad)}" '
        f'stroke="{SVG_BORDER}" stroke-opacity="{SVG_BORDER_A}" stroke-width="1"/>')
    y += 6.0
    for lines in notes:
        for k, line in enumerate(lines):
            chrome.append(svg_text(l_x + l_pad, y + note_fs * 0.82 + k * lead,
                                   line, note_fs, SVG_DIM))
        y += lead * len(lines) + 5.0

    # --- crop to what was actually drawn: circles with their radius, label boxes, the
    # two panels. The frame above is only a working surface; this is the picture.
    drawn = [(cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1) for cx, cy, r in obstacles]
    drawn += [(b[0] - LBL_HALO, b[1] - LBL_HALO, b[2] + LBL_HALO, b[3] + LBL_HALO)
              for _, _, b in seated.values()]
    drawn += list(panels)
    vx = min(b[0] for b in drawn) - SVG_CROP
    vy = min(b[1] for b in drawn) - SVG_CROP
    vw = max(b[2] for b in drawn) + SVG_CROP - vx
    vh = max(b[3] for b in drawn) + SVG_CROP - vy

    doc = "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_num(vw)}" '
        f'height="{svg_num(vh)}" viewBox="{svg_num(vx)} {svg_num(vy)} '
        f'{svg_num(vw)} {svg_num(vh)}">',
        f'<title>{svg_escape(SVG_TITLE)} — {svg_escape(SVG_SUB)}</title>',
        '<desc>Schematische Karte der DORA-Regulatorik: DORA im Zentrum, umgeben von '
        'den Kreisen der delegierten Rechtsakte, Leitlinien und Standards; Farbe '
        'steht für die Verbindlichkeit der Quelle.</desc>',
        f'<rect x="{svg_num(vx)}" y="{svg_num(vy)}" width="{svg_num(vw)}" '
        f'height="{svg_num(vh)}" fill="{SVG_BG}"/>',
        '<g id="kanten">', *edge_parts, '</g>',
        '<g id="anbindung">', *leaders, '</g>',
        '<g id="knoten">', *containers, *dots, '</g>',
        '<g id="beschriftung-halo">', *halos, '</g>',
        '<g id="beschriftung">', *labels, '</g>',
        '<g id="rahmen">', *chrome, '</g>',
        '</svg>',
        '',
    ])

    # --- what the picture is worth: fill, seating, contrast
    boxes = [b for _, _, b in seated.values()]
    clashes = sum(1 for a in range(len(boxes) - 1) for b in range(a + 1, len(boxes))
                  if boxes_overlap(boxes[a], boxes[b]))
    on_nodes = sum(1 for b in boxes for c in obstacles if box_hits_circle(b, *c))
    on_panels = sum(1 for b in boxes for p in panels if boxes_overlap(b, p))
    home = sum(1 for i, (lx, ly, _) in seated.items()
               if abs(lx - spots[i][0]) < 0.01 and ly < spots[i][1])
    label_cols = {colour.get(n["g"], "#8a8f98") for n in nodes if n.get("k")}
    contrasts = {c: round(contrast_ratio(c, SVG_BG), 2)
                 for c in sorted(label_cols | {SVG_FG, SVG_DIM})}
    stats = {
        "skalierung": round(scale, 3),
        "bild": [round(vw), round(vh)],
        "seitenverhaeltnis": round(vw / vh, 3),
        "graph_px": [round(ext_w * scale), round(ext_h * scale)],
        "graph_anteil_breite": f"{100 * ext_w * scale / vw:.0f}%",
        "elemente": {
            "kantenpfade": len(edge_parts),
            "container": len(containers),
            "punkte": len(dots),
            "beschriftungen": len(labels),
            "halos": len(halos),
            "anbindungen": len(leaders),
            "rahmen": len(chrome),
        },
        "kanten_gezeichnet": {"verweis": len(plain), "ganz": len(sup_full),
                              "teilweise": len(sup_part)},
        "beschriftung": {
            "ueber_dem_kreis": f"{home}/{len(boxes)}",
            "ueberlappt_label": clashes,
            "ueberlappt_knoten": on_nodes,
            "ueberlappt_panel": on_panels,
        },
        "legende_hoehe": round(l_h, 1),
        "kontrast_gegen_grund": contrasts,
        "min_kontrast": round(min(contrasts.values()), 2),
    }
    return doc, stats


def container_label(title: str) -> str:
    return title.split(" (")[0].strip()


def load_graph(path: Path) -> tuple[list[dict], list[tuple[int, int]], dict[tuple[int, int], int], dict]:
    """Turn graph.json into the record/edge shape the layout chain works on.

    Node order is taken over unchanged: it seeds the force pass, so preserving it is
    what makes a rebuild reproduce the previous picture.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    index = {n["id"]: i for i, n in enumerate(data["nodes"])}
    records = []
    for n in data["nodes"]:
        records.append({
            "t": n["title"],
            "d": n["date"],
            "g": n["group"],
            "rid": n["id"],
            "hub": n["kind"] == "container",
            "size": n.get("size", 0),
            "sized": bool(n.get("sized")),
            "partial": bool(n.get("size_estimated")),
            "part_of": index.get(n["container"]) if n.get("container") else None,
        })
    pairs: set[tuple[int, int]] = set()
    kinds: dict[tuple[int, int], int] = {}
    for e in data["edges"]:
        a, b = index[e["source"]], index[e["target"]]
        key = (min(a, b), max(a, b))
        pairs.add(key)
        kind = SUPERSEDED_KIND.get(e["type"], E_REF)
        if kind != E_REF:
            kinds[key] = kind
    return records, sorted(pairs), kinds, data["meta"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render docs/index.html from data/graph.json.")
    ap.add_argument("--graph", type=Path, default=Path("data/graph.json"),
                    help="metadata graph to read (default: %(default)s)")
    ap.add_argument("--out", type=Path, default=Path("docs/index.html"),
                    help="page to write (default: %(default)s)")
    ap.add_argument("--svg", type=Path, default=Path("docs/preview.svg"),
                    help="static preview image to write (default: %(default)s)")
    ap.add_argument("--report", type=Path, default=None,
                    help="write the geometry report to this file instead of stdout")
    args = ap.parse_args(argv)

    records, edges, edge_kinds, meta = load_graph(args.graph)
    palette = [[p["key"], p["colour"], p["label"]] for p in meta["palette"]]
    t0 = meta["timeline"]["start"]

    # --- containers and their members (packed first: their radii set the free-node cap)
    members: dict[int, list[int]] = {}
    for i, r in enumerate(records):
        if r["part_of"] is not None:
            members.setdefault(r["part_of"], []).append(i)
    container_idx = [i for i, r in enumerate(records) if r["hub"]]
    offsets: dict[int, list[tuple[float, float]]] = {}
    cont_r: dict[int, float] = {}
    for ci in container_idx:
        pts, rad = phyllotaxis(len(members.get(ci, [])), R_UNIT, UNIT_GAP)
        offsets[ci] = pts
        cont_r[ci] = rad

    radii, rstats = compute_radii(records, cont_r)

    # --- reduced layout graph: containers + free nodes
    owner = {}
    for ci, ms in members.items():
        for m in ms:
            owner[m] = ci
    bodies = [i for i in range(len(records)) if i in cont_r or (i not in owner and not records[i]["hub"])]
    bpos = {b: k for k, b in enumerate(bodies)}
    body_r = [radii[b] for b in bodies]   # containers already carry their packing radius
    bedges = set()
    for a, b in edges:
        ra = owner.get(a, a)
        rb = owner.get(b, b)
        if ra != rb and ra in bpos and rb in bpos:
            bedges.add((min(bpos[ra], bpos[rb]), max(bpos[ra], bpos[rb])))

    by_rid_all = {records[i]["rid"]: i for i in range(len(records)) if records[i]["rid"]}
    hints = []
    hint_groups: dict[str, int] = {}
    for grp, target_rid in GROUP_HINTS.items():
        ti = by_rid_all.get(target_rid)
        if ti is None or ti not in bpos:
            continue
        hint_groups[grp] = bpos[ti]
        for i in bodies:
            if records[i]["g"] == grp and i != ti:
                hints.append((bpos[i], bpos[ti]))

    pos = fit_into_box(layout(len(bodies), sorted(bedges), body_r, hints=hints),
                       DESIGN_W, DESIGN_H)
    _, ov_before = resolve_collisions(pos, body_r, BODY_GAP, rounds=0)
    loose, ov_after = resolve_collisions(pos, body_r, BODY_GAP)

    def body_name(k: int) -> str:
        r = records[bodies[k]]
        return container_label(r["t"]) if r["hub"] else r["t"]

    # centralise, then let the collision pass make room again: displaced neighbours
    # give way rather than the pulled-in container overlapping them
    forced = {bpos[i]: CENTRE_PULL[records[i]["rid"]]
              for i in range(len(records)) if records[i]["rid"] in CENTRE_PULL and i in bpos}
    pulled, com = centralise(loose, body_r, sorted(bedges), forced)
    centred, ov_centre = resolve_collisions(pulled, body_r, BODY_GAP)

    dora_b = by_rid_all[IMPACT_ID]
    dora_k = bpos[dora_b]
    budget = LEASH_FACTOR * body_r[dora_k]
    cont_ks = [bpos[i] for i in container_idx]
    ring_ks = [k for k in cont_ks if k != dora_k]

    # Compact and leash before the ring is turned: a body that still has slack would be
    # rotated with the wrong neighbourhood and would have to travel back across the
    # picture afterwards. Once everything sits where its edges want it, the turn carries
    # each act and its documents together.
    free_bodies = {k for k in range(len(bodies)) if bodies[k] not in cont_r}
    stage: dict[str, dict] = {}

    def note(label: str, pts) -> None:
        g = angular_gaps(pts, ring_ks, pts[dora_k])
        stage[label] = {"max_winkelluecke": round(max(g), 1),
                        "max_abstand_zum_nachbarn": round(max(
                            min(math.hypot(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1])
                                - body_r[i] - body_r[j] for j in linked_bodies[i])
                            for i in range(len(bodies)) if linked_bodies[i]), 1)}

    linked_bodies: dict[int, list[int]] = {k: [] for k in range(len(bodies))}
    for a, b in sorted(bedges):
        linked_bodies[a].append(b)
        linked_bodies[b].append(a)

    # The acts hold still while the documents are drawn in: left free, the largest
    # circles get squeezed out of the swarm that wants to sit on their rim, and DORA —
    # the body every bearing is measured from — drifts to the edge.
    held = frozenset(cont_ks)
    note("1_nach_zentralisierung", centred)
    packed = compact_free(centred, body_r, sorted(bedges), free_bodies, BODY_GAP, frozen=held)
    note("2_nach_verdichtung", packed)
    leashed, leash_one = leash(packed, body_r, sorted(bedges), budget, BODY_GAP)
    note("3_nach_leine", leashed)
    gaps_before = angular_gaps(leashed, ring_ks, leashed[dora_k])
    sym = symmetrise(leashed, body_r, ring_ks, dora_k, BODY_GAP)
    note("4_nach_symmetrie", sym)

    # Reshape toward the canvas: wider by the same factor that makes it flatter, so the
    # packed area stays put and only its proportions change. That is what buys size —
    # widening alone would only spread the picture, while the fit still answers to the
    # height. It happens before the last passes on purpose: the reshape pulls linked
    # bodies apart, and the leash has to hold in the picture that ships.
    def box(pts):
        return (min(pts[k][0] - body_r[k] for k in range(len(bodies))),
                max(pts[k][0] + body_r[k] for k in range(len(bodies))),
                min(pts[k][1] - body_r[k] for k in range(len(bodies))),
                max(pts[k][1] + body_r[k] for k in range(len(bodies))))

    # Every turn ends in a shippable state — reshaped, compacted, leashed and re-seated —
    # so the next turn measures the format the viewer will really get and only corrects
    # what the settling passes gave back.
    solved, factors, ov_squeeze, ov_stretch = sym, [], 0, 0
    leash_two = leash_three = {}
    for turn in range(ASPECT_ROUNDS):
        x0, x1, y0, y1 = box(solved)
        f = min(max(math.sqrt(ASPECT_TARGET * (y1 - y0) / (x1 - x0)), 1.0), ASPECT_CAP)
        factors.append(round(f, 3))
        if f <= 1.004:
            break
        mid_x, mid_y = (x0 + x1) / 2, (y0 + y1) / 2
        solved = [[mid_x + (p[0] - mid_x) * f, mid_y + (p[1] - mid_y) / f] for p in solved]
        _, ov = resolve_collisions(solved, body_r, BODY_GAP, rounds=0)
        ov_squeeze = max(ov_squeeze, ov)
        solved, ov_stretch = resolve_collisions(solved, body_r, BODY_GAP)
        note(f"5_{turn + 1}_nach_formatanpassung", solved)
        solved = compact_free(solved, body_r, sorted(bedges), free_bodies, BODY_GAP, frozen=held)
        solved, leash_two = leash(solved, body_r, sorted(bedges), budget, BODY_GAP,
                                  frozen=frozenset([dora_k]))
        solved = dock_hints(solved, body_r, hints, budget, BODY_GAP, frozen=held)
        solved, leash_three = leash(solved, body_r, sorted(bedges), budget, BODY_GAP, frozen=held)
        note(f"6_{turn + 1}_verdichtet_geleint_gesetzt", solved)
    stretch = factors[0]
    _, ov_compact = resolve_collisions(solved, body_r, BODY_GAP, rounds=0)
    solved, strays = pull_strays(solved, body_r, sorted(bedges), BODY_GAP)
    gaps_after = angular_gaps(solved, ring_ks, solved[dora_k])
    gaps_wide = gaps_after

    # the stock DORA hits: everything the corpus already held when the regulation landed
    dora_date = records[dora_b]["d"]
    stock_ks = [k for k in range(len(bodies)) if records[bodies[k]]["d"] < dora_date]
    pre, pre_stats = pre_impact_layout(solved, body_r, stock_ks, solved[dora_k], PRE_GAP)
    _, ov_pre = resolve_collisions([list(pre[k]) for k in stock_ks],
                                   [body_r[k] for k in stock_ks], BODY_GAP, rounds=0)
    impact_reach = max((math.hypot(solved[k][0] - solved[dora_k][0],
                                   solved[k][1] - solved[dora_k][1]) + body_r[k]
                        for k in stock_ks), default=body_r[dora_k])

    # labels: once for the solved picture, once for the pre-impact pack
    label_text = {k: container_label(records[bodies[k]]["t"]) for k in cont_ks}
    labels, label_clashes = place_labels(solved, body_r, cont_ks, label_text)
    pre_cont = [k for k in cont_ks if k in pre]
    pre_pts = {k: pre[k] for k in pre_cont}
    pre_labels, pre_label_clashes = place_labels(pre_pts, body_r, pre_cont, label_text)

    def to_centre(pts, k: int) -> float:
        return math.hypot(pts[k][0] - com[0], pts[k][1] - com[1])

    centre_report = {
        body_name(k): {"vorher": round(to_centre(loose, k), 1),
                       "nachher": round(to_centre(solved, k), 1)}
        for k in sorted(forced)
    }
    ranked = sorted(range(len(bodies)), key=lambda k: -body_r[k])[:6]
    centre_top = {body_name(k): {"vorher": round(to_centre(loose, k), 1),
                                 "nachher": round(to_centre(solved, k), 1)}
                  for k in ranked}

    # --- neighbourhood and slack metrics
    def rim(pts, a: int, b: int) -> float:
        return math.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1]) - body_r[a] - body_r[b]

    hint_report = {}
    for grp, ti in hint_groups.items():
        ks = [bpos[i] for i in bodies if records[i]["g"] == grp and bpos[i] != ti]
        if not ks:
            continue
        hint_report[f"{grp} -> {body_name(ti)}"] = {
            "objekte": len(ks),
            "max_vorher": round(max(rim(loose, k, ti) for k in ks), 1),
            "max_nachher": round(max(rim(solved, k, ti) for k in ks), 1),
            "median_nachher": round(sorted(rim(solved, k, ti) for k in ks)[len(ks) // 2], 1),
        }

    linked_b: dict[int, list[int]] = {k: [] for k in range(len(bodies))}
    for a, b in bedges:
        linked_b[a].append(b)
        linked_b[b].append(a)

    def slack(pts, k: int) -> float:
        return min(rim(pts, k, j) for j in linked_b[k]) if linked_b[k] else 0.0

    linked_all = [k for k in range(len(bodies)) if linked_b[k]]
    linked_free = [k for k in free_bodies if linked_b[k]]
    outliers = sorted(((slack(solved, k), body_name(k)) for k in linked_all), reverse=True)[:4]
    slack_report = {
        "richtwert_1_5x_dora_radius": round(budget, 1),
        "max_vorher": round(max(slack(loose, k) for k in linked_all), 1),
        "max_nachher": round(max(slack(solved, k) for k in linked_all), 1),
        "median_nachher": round(sorted(slack(solved, k) for k in linked_free)[len(linked_free) // 2], 1),
        "ueber_richtwert_vorher": sum(1 for k in linked_all if slack(loose, k) > budget),
        "ueber_richtwert_nachher": sum(1 for k in linked_all if slack(solved, k) > budget),
        "weiteste_nachher": [{"koerper": nm, "abstand": round(s, 1)} for s, nm in outliers],
    }
    watch = next((k for k in linked_all if body_name(k).startswith("Verordnung 1025")), None)
    if watch is not None:
        slack_report["verordnung_1025_2012"] = {
            "vorher": round(slack(loose, watch), 1),
            "nach_zentralisierung": round(slack(centred, watch), 1),
            "nachher": round(slack(solved, watch), 1),
        }

    for s in strays:
        s["koerper"] = [body_name(k) for k in s["koerper"]]
    degree = [0] * len(bodies)
    for a, b in bedges:
        degree[a] += 1
        degree[b] += 1
    edgeless = [body_name(k) for k in range(len(bodies)) if degree[k] == 0]

    # --- final coordinates
    xy: list[tuple[float, float]] = [(0.0, 0.0)] * len(records)
    for b, k in bpos.items():
        xy[b] = (solved[k][0], solved[k][1])
    for ci, ms in members.items():
        cx, cy = xy[ci]
        for k, m in enumerate(sorted(ms)):
            dx, dy = offsets[ci][k]
            xy[m] = (cx + dx, cy + dy)
    xy_pre = {bodies[k]: pre[k] for k in stock_ks}

    # --- extent: both layouts and both label passes have to fit
    def reach(i: int) -> float:
        return cont_r[i] if i in cont_r else radii[i]

    spots = [(xy[i][0], xy[i][1], reach(i)) for i in range(len(records))]
    spots += [(p[0], p[1], radii[i]) for i, p in xy_pre.items()]
    for src, pts in ((labels, solved), (pre_labels, pre)):
        for k, (ox, oy) in src.items():
            w, h = label_box(label_text[k])
            spots.append((pts[k][0] + ox, pts[k][1] + oy, max(w, h) / 2))
    minx = min(s[0] - s[2] for s in spots)
    maxx = max(s[0] + s[2] for s in spots)
    miny = min(s[1] - s[2] for s in spots)
    maxy = max(s[1] + s[2] for s in spots)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    ext_w, ext_h = (maxx - minx) + 12, (maxy - miny) + 12

    nodes = []
    for i, r in enumerate(records):
        node = {
            "t": container_label(r["t"]) if r["hub"] else r["t"],
            "d": r["d"], "g": r["g"], "s": r["size"], "p": 1 if r["partial"] else 0,
            "r": round(radii[i], 2),
            "x": round(xy[i][0] - cx, 1), "y": round(xy[i][1] - cy, 1),
        }
        if i in cont_r:
            node["k"] = 1
            node["cr"] = round(cont_r[i], 2)
            ox, oy = labels[bpos[i]]
            node["lx"], node["ly"] = round(ox, 1), round(oy, 1)
        if i in owner:
            node["c"] = owner[i]
        if i in xy_pre:
            node["px"] = round(xy_pre[i][0] - cx, 1)
            node["py"] = round(xy_pre[i][1] - cy, 1)
            if i in cont_r:
                ox, oy = pre_labels[bpos[i]]
                node["qx"], node["qy"] = round(ox, 1), round(oy, 1)
        nodes.append(node)

    payload = {
        "generated": meta["generated"],
        "palette": palette,
        "extent": [round(ext_w, 1), round(ext_h, 1)],
        "t0": t0,
        "impact": {"k": dora_b, "d": dora_date, "dur": IMPACT_SECONDS,
                   "reach": round(impact_reach, 1)},
        "nodes": nodes,
        "edges": [[a, b] + ([edge_kinds[(a, b)]] if (a, b) in edge_kinds else [])
                  for a, b in edges],
    }
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(HTML.replace("__DATA__", blob), encoding="utf-8")

    # the same payload a second time, as the still image the README can show
    svg, svg_stats = render_preview(payload)
    args.svg.parent.mkdir(parents=True, exist_ok=True)
    args.svg.write_text(svg, encoding="utf-8")

    # --- checks
    bad_containment = []
    for ci, ms in members.items():
        for m in ms:
            d = math.hypot(xy[m][0] - xy[ci][0], xy[m][1] - xy[ci][1])
            if d + radii[m] > cont_r[ci] + 1e-6:
                bad_containment.append(records[m]["stem"])
    cross = {"container_container": 0, "container_frei": 0, "frei_frei": 0}
    is_cont = [bodies[k] in cont_r for k in range(len(bodies))]
    for a in range(len(bodies) - 1):
        for b in range(a + 1, len(bodies)):
            d = math.hypot(solved[a][0] - solved[b][0], solved[a][1] - solved[b][1])
            if d < body_r[a] + body_r[b]:
                key = ("container_container" if is_cont[a] and is_cont[b]
                       else "frei_frei" if not is_cont[a] and not is_cont[b]
                       else "container_frei")
                cross[key] += 1
    unit_idx = sorted(owner)
    cross["einheit_einheit"] = sum(
        1
        for a in range(len(unit_idx) - 1)
        for b in range(a + 1, len(unit_idx))
        if math.hypot(xy[unit_idx[a]][0] - xy[unit_idx[b]][0],
                      xy[unit_idx[a]][1] - xy[unit_idx[b]][1])
        < radii[unit_idx[a]] + radii[unit_idx[b]]
    )
    unit_radii = sorted({round(radii[i], 3) for i in unit_idx})

    # what the JS fit makes of the extent on a common desktop viewport
    def fit_at(vw: float, vh: float, legend: bool) -> dict:
        avail_w = max(vw - 30 - (330 if legend else 30), 120)
        avail_h = max(vh - 104 - 96, 120)
        s = min(avail_w / ext_w, avail_h / ext_h)
        return {"skalierung": round(s, 3),
                "bild_px": [round(ext_w * s), round(ext_h * s)],
                "flaeche_genutzt": f"{100 * (ext_w * s) * (ext_h * s) / (avail_w * avail_h):.0f}%"}

    dates = sorted(r["d"] for r in records if r["d"])
    cr_sorted = sorted(((cont_r[i], container_label(records[i]["t"]), len(members.get(i, [])))
                        for i in container_idx), reverse=True)
    report = {
        "out": str(args.out),
        "bytes": args.out.stat().st_size,
        "vorschau": dict(datei=str(args.svg), bytes=args.svg.stat().st_size, **svg_stats),
        "nodes": len(nodes),
        "edges": len(edges),
        "container": len(container_idx),
        "mitglieder": sum(len(v) for v in members.values()),
        "freie_knoten": len(bodies) - len(container_idx),
        "verdraengungskanten": {
            container_label(records[a]["t"]) + " -> " + container_label(records[b]["t"]):
                ("ganz" if k == E_SUPER else "teilweise")
            for (a, b), k in sorted(edge_kinds.items())
        },
        "unverbunden": {"kantenlose_koerper": edgeless, "herangerueckt": strays},
        "zentralisierung": {"gezielt": centre_report, "groesste_container": centre_top},
        "nachbarschaft": hint_report,
        "verdichtung": slack_report,
        "leine": {"erster_pass": leash_one, "nach_verdichtung": leash_two,
                  "nach_nachbarschaft": leash_three},
        "symmetrie": {
            "container_im_ring": len(ring_ks),
            "gleichverteilung_grad": round(360 / len(ring_ks), 1) if ring_ks else None,
            "max_luecke_vorher": round(max(gaps_before), 1),
            "max_luecke_nachher": round(max(gaps_after), 1),
            "min_luecke_vorher": round(min(gaps_before), 1),
            "min_luecke_nachher": round(min(gaps_after), 1),
            "streuung_vorher": round(
                (sum((g - 360 / len(ring_ks)) ** 2 for g in gaps_before) / len(gaps_before)) ** 0.5, 1),
            "streuung_nachher": round(
                (sum((g - 360 / len(ring_ks)) ** 2 for g in gaps_after) / len(gaps_after)) ** 0.5, 1),
            "je_stufe": stage,
        },
        "einschlag": dict(pre_stats, datum=dora_date, sekunden=IMPACT_SECONDS,
                          ringreichweite=round(impact_reach, 1),
                          ueberlappungen_vorlayout=ov_pre),
        "labels": {"container": len(labels), "ueberlappungen_end": label_clashes,
                   "ueberlappungen_vorlayout": pre_label_clashes,
                   "nicht_oben": sum(1 for ox, oy in labels.values() if abs(ox) > 0.01)},
        "bildfuellung": {
            "formatfaktoren": factors,
            "ueberlappungen_durch_stauchung": ov_squeeze,
            "ueberlappungen_nach_ausgleich": ov_stretch,
            "extent": [round(ext_w, 1), round(ext_h, 1)],
            "1600x1000_legende_offen": fit_at(1600, 1000, True),
            "1600x1000_legende_zu": fit_at(1600, 1000, False),
        },
        "radius": rstats,
        "container_radien": [{"akt": n, "r": round(r, 1), "einheiten": m} for r, n, m in cr_sorted],
        "checks": {
            "containment_verletzt": bad_containment,
            "koerper_ueberlappungen_vorher": ov_before,
            "koerper_ueberlappungen_nachher": ov_after,
            "koerper_ueberlappungen_nach_zentralisierung": ov_centre,
            "koerper_ueberlappungen_nach_verdichtung": ov_compact,
            "koerper_ueberlappungen_final": cross,
            "einheitsradien": unit_radii,
            "freie_unter_deckel": rstats["regel_eingehalten"],
        },
        "zeitachse": {"t0": t0, "spanne": [dates[0], dates[-1]] if dates else None,
                      "vor_t0_sichtbar_ab_start": sum(1 for r in records if r["d"] and r["d"] < t0)},
        "design_extent": [round(ext_w, 1), round(ext_h, 1)],
    }
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
