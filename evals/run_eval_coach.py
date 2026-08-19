"""
Evaluation harness for the LIVE AI Coach Report path.

evals/run_eval.py covers run_strategic_agent (the legacy 3-card report, not
wired to any page). This one covers run_ai_coach_report_agent — the pipeline
actually behind the "RUN AI COACH REPORT" button on Player Review.

Measures the same thing that mattered most for the strategic path: is the
advice something a player can execute next game, or is it correct-but-unusable?
For this report the action-bearing sections are PRACTICE ASSIGNMENT (the drill)
and TURNING POINTS (the replay checklist).

Usage:
    python evals/run_eval_coach.py --out coach_before
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from features.coaching.agents import (
    AI_COACH_LABELS,
    _clean_output,
    _draft_ai_coach_report,
    _retrieve_ai_coach_context,
)
from features.coaching.validators import (
    check_actionability,
    count_match_anchors,
    find_role_nonsense,
    find_template_leaks,
    judge_ai_coach_output,
    score_action,
    section_text,
)
from evals.run_eval import build_rich_match_state
from utils.cloud_llm import api_available


# Metrics each position is actually graded on — mirrors POSITION_METRICS in
# services/execution_service.py. Without this the eval hands the model a
# primary failure the live app would never produce (e.g. CS/min for a support),
# and the model faithfully repeats it.
POSITION_GRADED_ON = {
    "UTILITY": ("vision", "kill participation", "deaths"),
    "JUNGLE": ("kill participation", "vision", "cs/min", "deaths"),
    "MIDDLE": ("cs/min", "kill participation", "vision", "deaths"),
    "TOP": ("cs/min", "deaths", "damage share", "vision"),
    "BOTTOM": ("cs/min", "deaths", "damage share", "kda"),
}


def _primary_failure(below: str, position: str) -> str:
    """Pick the first below-benchmark metric this ROLE is actually graded on."""
    if below == "none listed":
        return "No single primary failure detected"
    graded = POSITION_GRADED_ON.get((position or "").upper(), ())
    for part in below.split(","):
        name = part.split("(", 1)[0].strip().lower()
        if any(g in name for g in graded):
            return part.strip()
    return "No single primary failure detected"


def build_coach_context(state: dict) -> str:
    """Approximate the deterministic packet pages/2_Player_Review.py assembles."""
    below = state["below_avg"]
    primary = _primary_failure(below, state["position"])
    above = state["above_avg"]
    positive = above.split(",")[0].strip() if above != "none listed" else "none recorded"
    return (
        f"Coach Diagnosis: Primary review anchor is {primary}.\n"
        f"Primary Failure: {primary}\n"
        f"Positive Signal: {positive}\n"
        f"Role Responsibility: {state['champion']} {state['position']} must deliver the job its role is graded on.\n"
        f"Match Metrics: {state['match_data']}\n"
        f"Data Health: Confidence MEDIUM; timeline frames unavailable, lane facts derived from challenges block.\n"
        f"Replay Checkpoints: review first death and first objective setup.\n"
        f"One Priority Fix: address {primary} before secondary gaps."
    )


def score_report(draft: str, state: dict) -> dict:
    """Actionability for this report shape: the drill plus replay checklist."""
    assignment = section_text(draft, "PRACTICE ASSIGNMENT", AI_COACH_LABELS)
    turning = section_text(draft, "TURNING POINTS", AI_COACH_LABELS)
    a_score = score_action(assignment)
    # Turning-point bullets each act as an instruction to check in replay.
    t_lines = [ln.strip("- ").strip() for ln in turning.splitlines() if ln.strip().startswith("-")]
    t_scores = [score_action(ln) for ln in t_lines]
    return {
        "assignment_text": assignment[:300],
        "assignment_actionable": a_score["actionable"],
        "assignment_has_trigger": a_score["has_trigger"],
        "assignment_has_target": a_score["has_target"],
        "assignment_vague_opener": a_score["starts_vague"],
        "turning_points": len(t_scores),
        "turning_actionable": sum(t["actionable"] for t in t_scores),
    }


def run_one(state: dict) -> dict:
    coach_state = {
        "coach_context": build_coach_context(state),
        "match_data": state["match_data"],
        "timeline_data": state["timeline_data"],
        "champion": state["champion"],
        "position": state["position"],
        "routing_query": "",
        "repair_count": 0,
    }
    coach_state.update(_retrieve_ai_coach_context(coach_state))
    t0 = time.perf_counter()
    coach_state.update(_draft_ai_coach_report(coach_state))
    latency = time.perf_counter() - t0
    draft = coach_state["draft"]

    passed, feedback = judge_ai_coach_output(coach_state)
    return {
        "match_id": state["match_id"], "champion": state["champion"],
        "position": state["position"], "win": state["win"],
        "draft": draft,
        "passed_reflection": passed, "feedback": feedback,
        "match_anchors": count_match_anchors(draft, state["match_data"], state["champion"]),
        "template_leaks": len(find_template_leaks(draft)),
        "role_nonsense": len(find_role_nonsense(draft, state["position"])),
        "word_count": len(draft.split()),
        "latency": round(latency, 2),
        **score_report(draft, state),
    }


def summarize(results: list[dict]) -> dict:
    n = len(results) or 1
    return {
        "n_matches": len(results),
        "backend": "cloud (gpt-4o-mini)" if api_available() else "local ollama",
        "reflection_pass_rate": sum(r["passed_reflection"] for r in results) / n,
        "actionability": {
            "assignment_actionable_rate": sum(r["assignment_actionable"] for r in results) / n,
            "assignment_has_trigger_rate": sum(r["assignment_has_trigger"] for r in results) / n,
            "assignment_has_target_rate": sum(r["assignment_has_target"] for r in results) / n,
            "assignment_vague_opener_rate": sum(r["assignment_vague_opener"] for r in results) / n,
            "turning_actionable_rate": (
                sum(r["turning_actionable"] for r in results) / max(sum(r["turning_points"] for r in results), 1)
            ),
        },
        "content": {
            "avg_match_anchors": round(sum(r["match_anchors"] for r in results) / n, 2),
            "template_leak_rate": sum(1 for r in results if r["template_leaks"]) / n,
            "role_nonsense_rate": sum(1 for r in results if r["role_nonsense"]) / n,
        },
        "avg_word_count": round(sum(r["word_count"] for r in results) / n),
        "latency_p50": round(median([r["latency"] for r in results]), 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="coach")
    args = ap.parse_args()

    from features.player_review.benchmarks import get_position_benchmark
    pool = json.loads((ROOT / "data" / "sample_matches.json").read_text())
    records = json.loads((ROOT / "evals" / "eval_matches_rich.json").read_text())

    results = []
    for i, rec in enumerate(records):
        p = rec["participant"]
        bench, _ = get_position_benchmark(pool, p["championName"], p["teamPosition"])
        state = build_rich_match_state(rec, bench)
        if not state:
            continue
        print(f"  [{i+1}/{len(records)}] {state['champion']:<12} {state['position']:<8} ...", flush=True)
        results.append(run_one(state))

    summary = summarize(results)
    out = ROOT / "evals" / "results"
    out.mkdir(exist_ok=True)
    (out / f"raw_{args.out}.json").write_text(json.dumps(results, indent=2))
    (out / f"summary_{args.out}.json").write_text(json.dumps(summary, indent=2))
    print("\n" + json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
