"""
Extract a compact eval set from the full local match dataset.

The committed demo dataset (data/sample_matches.json) is privacy-stripped: no
timeline, no `challenges` block, so the coaching prompt has nothing to say
about lane phase and the model correctly answers "unclear from available data".
The full local dataset carries Riot's `challenges` block, which includes the
lane-phase facts (CS@10, CS advantage, gold/XP lead, plates) that the stripped
set is missing.

This writes evals/eval_matches_rich.json — same 20-slot sampling design as
select_matches.py, but keeping the rich per-participant fields so the eval can
answer: how much of the "generic report" problem is a data-availability
problem rather than a model problem?

Usage:
    python evals/extract_rich.py --source /path/to/challenger_matches.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

KEEP_CHALLENGES = (
    "laneMinionsFirst10Minutes", "maxCsAdvantageOnLaneOpponent",
    "laningPhaseGoldExpAdvantage", "earlyLaningPhaseGoldExpAdvantage",
    "maxLevelLeadLaneOpponent", "turretPlatesTaken", "soloKills",
    "killsNearEnemyTurret", "jungleCsBefore10Minutes", "dragonTakedowns",
    "riftHeraldTakedowns", "baronTakedowns", "teamDamagePercentage",
    "damageTakenOnTeamPercentage", "killParticipation",
    "visionScoreAdvantageLaneOpponent", "controlWardsPlaced", "wardTakedowns",
)
KEEP_FIELDS = (
    "championName", "teamPosition", "teamId", "win", "kills", "deaths",
    "assists", "totalMinionsKilled", "neutralMinionsKilled",
    "totalDamageDealtToChampions", "visionScore", "totalTimeSpentDead",
    "wardsPlaced", "wardsKilled", "detectorWardsPlaced",
)

N_MATCHES = 20


def _stream_matches(path: Path, limit: int):
    """Yield match objects one at a time without loading the whole file."""
    with path.open() as f:
        assert f.read(1) == "["
        buf, depth, started, count = [], 0, False, 0
        while count < limit:
            c = f.read(1)
            if not c:
                break
            if c == "{":
                depth += 1
                started = True
            if started:
                buf.append(c)
            if c == "}":
                depth -= 1
                if depth == 0 and started:
                    yield json.loads("".join(buf))
                    buf, started, count = [], False, count + 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--stride", type=int, default=7)
    args = ap.parse_args()

    src = Path(args.source)
    picks = []
    for i, match in enumerate(_stream_matches(src, N_MATCHES * args.stride)):
        if i % args.stride:
            continue
        idx = (i // args.stride) % 10
        parts = match["info"].get("participants", [])
        if idx >= len(parts):
            continue
        p = parts[idx]
        if not p.get("challenges") or p.get("teamPosition") in (None, "", "UNKNOWN"):
            continue
        team = [
            {k: pp.get(k) for k in ("teamId", "kills", "totalDamageDealtToChampions")}
            for pp in parts if pp.get("teamId") == p.get("teamId")
        ]
        picks.append({
            "match_id": match.get("metadata", {}).get("matchId", f"local_{i}"),
            "game_duration": match["info"].get("gameDuration", 0),
            "participant": {k: p.get(k) for k in KEEP_FIELDS},
            "challenges": {k: p["challenges"].get(k) for k in KEEP_CHALLENGES if k in p["challenges"]},
            "team": team,
        })
        if len(picks) >= N_MATCHES:
            break

    out = ROOT / "evals" / "eval_matches_rich.json"
    out.write_text(json.dumps(picks, indent=2))
    print(f"Wrote {len(picks)} rich matches -> {out} ({out.stat().st_size/1024:.0f} KB)")
    for p in picks:
        pt = p["participant"]
        print(f"  {p['match_id']}  {pt['championName']:<12} {pt['teamPosition']:<8} "
              f"{'WIN' if pt['win'] else 'LOSS'}")


if __name__ == "__main__":
    main()
