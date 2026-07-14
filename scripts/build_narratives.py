"""
Build the committed behavioral-narrative corpus.

Reads rich offline match JSON (summaries that include the Riot `challenges`
block) and writes a compact `data/challenger_narratives.json` of behavioral
narratives — what Challenger players actually DID, not the averages the app
already computes. The output is small enough to commit and is what powers RAG
retrieval on hosts without an embedding model (via the keyword fallback).

Usage:
    python scripts/build_narratives.py \
        --source /path/to/challenger_matches.json \
        --out data/challenger_narratives.json \
        --per-bucket 3 --max 1200
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.rag import build_behavior_narrative


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="Rich match JSON with challenges block")
    ap.add_argument("--out", default="data/challenger_narratives.json")
    ap.add_argument("--per-bucket", type=int, default=3,
                    help="Max narratives per (champion, position, win) bucket")
    ap.add_argument("--max", type=int, default=1200, help="Overall cap")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        print(f"Source not found: {src}")
        sys.exit(1)

    print(f"Loading {src} ...")
    with src.open() as f:
        matches = json.load(f)
    print(f"  {len(matches)} matches")

    bucket_counts: dict = defaultdict(int)
    out: list[dict] = []
    for match in matches:
        info = match.get("info", {})
        game_min = info.get("gameDuration", 0) / 60
        if game_min < 5:
            continue
        for p in info.get("participants", []):
            pos = p.get("teamPosition")
            if not pos or pos == "UNKNOWN":
                continue
            bucket = (p.get("championName", ""), pos, bool(p.get("win")))
            if bucket_counts[bucket] >= args.per_bucket:
                continue
            narrative = build_behavior_narrative(p, game_min)
            if not narrative:
                continue
            bucket_counts[bucket] += 1
            out.append({
                "content": narrative,
                "champion": p.get("championName", ""),
                "position": pos,
                "win": bool(p.get("win")),
                "source": "Challenger behavioral narrative",
            })
            if len(out) >= args.max:
                break
        if len(out) >= args.max:
            break

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(out, f, indent=0)
    size_kb = out_path.stat().st_size / 1024
    champs = len({d["champion"] for d in out})
    print(f"Wrote {len(out)} narratives ({champs} champions) → {out_path} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
