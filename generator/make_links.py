#!/usr/bin/env python3
"""Render LINKS.md — the searchable list of every source the graph points at.

Reads data/graph.json and nothing else. The output is byte-deterministic: fixed group
order, fixed sort inside each group, no timestamp, LF line endings — so CI can rebuild
the file and diff it against the committed one.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Group order and German headings. Any group the palette adds later still shows up,
# appended under its palette label, so a new rank cannot silently drop its rows.
HEADINGS = {
    "rang-1": "Rang 1 — bindendes Recht",
    "rang-2": "Rang 2 — RTS/ITS",
    "rang-3": "Rang 3 — Aufsichtserwartung",
    "rang-4": "Rang 4 — ESA-Q&As",
    "rang-5": "Rang 5 — vorbereitendes Material",
    "rang-6": "Rang 6 — datierte Aufsichtsveröffentlichung",
    "rang-7": "Rang 7 — laufende Aufsichtskommunikation",
    "standard": "Standards",
    "erwaegungsgrund": "Erwägungsgründe",
}


def escape(text: str) -> str:
    """Keep a title from breaking the table or turning into markup."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")


def render(data: dict) -> str:
    order = [p["key"] for p in data["meta"]["palette"]]
    labels = {p["key"]: p["label"] for p in data["meta"]["palette"]}
    nodes = data["nodes"]
    counts = data["meta"]["counts"]

    out: list[str] = [
        "# Quellen des DORA-Graphen",
        "",
        "Generiert aus `data/graph.json` durch `generator/make_links.py` — nicht von Hand",
        "bearbeiten. Jede Zeile verweist auf das Dokument beim Herausgeber; dieses",
        "Repository spiegelt keinen Normtext.",
        "",
        f"{counts['nodes']} Knoten · {counts['edges']} Kanten · {counts['containers']} Rechtsakte",
        "",
    ]

    for key in order:
        rows = [n for n in nodes if n["group"] == key]
        if not rows:
            continue
        # inside a group: by date, then by title, then by id — a total order, so the
        # file is the same on every machine
        rows.sort(key=lambda n: (n["date"], n["title"], n["id"]))
        out.append(f"## {HEADINGS.get(key, labels.get(key, key))}")
        out.append("")
        out.append("| Titel | Datum | Quelle |")
        out.append("| --- | --- | --- |")
        for n in rows:
            url = n.get("url")
            source = f"[{escape(n['id'])}]({url})" if url else "—"
            out.append(f"| {escape(n['title'])} | {n['date']} | {source} |")
        out.append("")

    return "\n".join(out).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render LINKS.md from data/graph.json.")
    ap.add_argument("--graph", type=Path, default=Path("data/graph.json"),
                    help="metadata graph to read (default: %(default)s)")
    ap.add_argument("--out", type=Path, default=Path("LINKS.md"),
                    help="file to write (default: %(default)s)")
    args = ap.parse_args(argv)

    data = json.loads(args.graph.read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(data))
    print(f"{args.out}: {args.out.stat().st_size} bytes, {len(data['nodes'])} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
