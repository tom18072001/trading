"""Extract every pick this system actually emailed, from the report HTML archive.

`report/daily_report_<date>.html` is the only durable record of what was
suggested on a given day -- PicksUniverseService keeps one snapshot (today's)
and nothing else. 19 reports survive (2026-07-23 .. 2026-09-10).

Output: a CSV of (report_date, symbol, side, source, score, entry, target, stop).
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "report"

CARD_RE = re.compile(
    r"<div class='snap-card'>(.*?)</div></div>", re.S)
SYM_RE = re.compile(r"class='sym'>([A-Z0-9]{3})<")
TAG_RE = re.compile(r"class='tag tag-(\w+)'>(\w+)<")
SRC_RE = re.compile(r"class='src-tag src-(\w+)'>([^<]*)<")
SCORE_RE = re.compile(r"score ([+-]?\d+)")
NUM_RE = re.compile(
    r"Giá <b>([\d.]+)</b>.*?Target ([\d.]+).*?Stop ([\d.]+)", re.S)
HEAD_RE = re.compile(r"<h3>(Nên MUA|Nên BÁN)[^<]*</h3>")


def parse_report(path: Path) -> list[dict]:
    html = path.read_text(encoding="utf-8")
    date = path.stem.replace("daily_report_", "")

    # The unified section is the single source of truth (CLAUDE.md sec2).
    start = html.find("UNIFIED PICKS")
    if start < 0:
        return []
    block = html[start:]
    # The section ends at the next <h2>; without this bound the SELL / HOLD /
    # WATCH cards of every later section get swallowed and mislabelled as BUY.
    nxt = block.find("<h2>", block.find("<h2>") + 1)
    if nxt > 0:
        block = block[:nxt]

    rows: list[dict] = []
    # Split into the MUA half and the BAN half so side is unambiguous.
    heads = list(HEAD_RE.finditer(block))
    for i, h in enumerate(heads):
        side = "BUY" if "MUA" in h.group(1) else "SELL"
        seg = block[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(block)]
        for card in re.finditer(r"<div class='snap-card'>(.*?)(?=<div class='snap-card'>|$)", seg, re.S):
            c = card.group(1)
            sym = SYM_RE.search(c)
            if not sym:
                continue
            nums = NUM_RE.search(c)
            sc = SCORE_RE.search(c)
            src = SRC_RE.search(c)
            rows.append({
                "date": date,
                "symbol": sym.group(1),
                "side": side,
                "source": (src.group(2).strip() if src else ""),
                "score": int(sc.group(1)) if sc else None,
                "entry": float(nums.group(1)) if nums else None,
                "target": float(nums.group(2)) if nums else None,
                "stop": float(nums.group(3)) if nums else None,
            })
    return rows


def main() -> int:
    out = ROOT / "data" / "past_picks.csv"
    allrows: list[dict] = []
    files = sorted(REPORT_DIR.glob("daily_report_*.html"))
    for f in files:
        r = parse_report(f)
        allrows.extend(r)
        print(f"{f.name}: {len(r)} picks")
    if not allrows:
        print("no picks parsed", file=sys.stderr)
        return 1
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(allrows[0].keys()))
        w.writeheader()
        w.writerows(allrows)
    print(f"\n{len(allrows)} picks from {len(files)} reports -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
