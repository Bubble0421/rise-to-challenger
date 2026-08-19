"""
Pick a fixed, reproducible set of matches for the eval harness.

Selection is deterministic: every Nth match from data/sample_matches.json,
rotating through participants to get position/champion diversity. Writes
evals/eval_matches.json as [{match_index, participant_index}, ...] — indices
into the committed sample dataset, not raw match IDs, so the eval stays
reproducible without depending on Riot's live API.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

N_MATCHES = 20
STRIDE = 900 // N_MATCHES  # spread across the whole 900-match file


def main() -> None:
    with (ROOT / "data" / "sample_matches.json").open() as f:
        matches = json.load(f)

    picks = []
    for i in range(N_MATCHES):
        match_index = (i * STRIDE) % len(matches)
        participant_index = i % 10  # rotate through all 10 slots for role/champ diversity
        match = matches[match_index]
        participant = match["info"]["participants"][participant_index]
        picks.append({
            "match_index": match_index,
            "participant_index": participant_index,
            "match_id": match["metadata"]["matchId"],
            "champion": participant["championName"],
            "position": participant.get("teamPosition", "UNKNOWN"),
            "win": participant["win"],
        })

    out_path = ROOT / "evals" / "eval_matches.json"
    with out_path.open("w") as f:
        json.dump(picks, f, indent=2)
    print(f"Wrote {len(picks)} fixed match picks -> {out_path}")
    for p in picks:
        print(f"  {p['match_id']}  {p['champion']:<12} {p['position']:<8} {'WIN' if p['win'] else 'LOSS'}")


if __name__ == "__main__":
    main()
