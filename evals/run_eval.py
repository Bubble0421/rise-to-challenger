"""
Evaluation harness for the coaching pipeline's contradiction problem.

Runs the real Strategic Coaching agent (features/coaching/agents.run_strategic_agent
internals) over a fixed set of 20 matches and measures, for two validator
configurations sharing the SAME drafted output per match:

  baseline — the legacy single-direction check that shipped before this session
             (only caught criticizing an above-average metric, and only in losses)
  v2       — the real, currently-shipped check_contradiction() (bidirectional,
             unconditional)

The key design point, carried over from the original brief: contradictions are
measured on every draft regardless of which config "acts" on them, so we can
show whether a config's pass rate was measuring the right thing.

Usage:
    python evals/run_eval.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from features.coaching.agents import (
    STRATEGIC_REPAIR_PROMPT,
    _build_coaching_context,
    _clean_output,
    _draft_coaching_report,
    _llm,
    _strategic_fallback,
)
from features.coaching.validators import (
    COACHING_LABELS,
    check_contradiction,
    has_number,
    has_colon_labels,
    has_vague_phrase,
    colon_label_values,
    mentions_critically,
    judge_coaching_output as judge_coaching_output_v2,
    check_content_quality,
    count_match_anchors,
    find_template_leaks,
    find_role_nonsense,
    check_actionability,
    extract_actions,
    score_action,
)
from utils.cloud_llm import api_available
MAX_CONTEXT_CHARS = 3_500

# Metrics judged higher-is-better vs lower-is-better, matching the app's own
# benchmark comparisons (features/player_review/benchmarks.py + execution_service.py).
HIGHER_IS_BETTER = ("kda", "cs_per_min", "vision", "kp", "damage_share")
LOWER_IS_BETTER = ("deaths",)
METRIC_LABELS = {
    "kda": "KDA", "cs_per_min": "CS/min", "vision": "vision",
    "kp": "kill participation", "damage_share": "damage share", "deaths": "deaths",
}


def judge_coaching_output_legacy(state: dict) -> tuple[bool, str]:
    """Reconstruction of judge_coaching_output as it shipped BEFORE this eval's
    fix — kept here (not in validators.py) purely so the eval can compare
    against it. Only checked one direction (criticizing a strength), and only
    inside a loss with both above- and below-average metrics present."""
    text = state.get("draft", "")
    labels = state.get("labels", COACHING_LABELS)
    issues = []
    if text.startswith("LLM unavailable"):
        issues.append("local model unavailable")
    if not has_colon_labels(text, labels):
        issues.append("missing required labels")
    if has_vague_phrase(text):
        issues.append("contains vague coaching language")
    if not has_number(text):
        issues.append("missing a concrete number")
    values = colon_label_values(text, labels)
    long_answers = [value for value in values if len(value.split()) > 56]
    if long_answers:
        issues.append("answers are too long for coaching cards")
    if values and not all("evidence" in value.lower() for value in values):
        issues.append("each answer must mark evidence")
    if values and not all(("meaning" in value.lower() or "unclear from available data" in value.lower()) for value in values):
        issues.append("each answer must explain meaning or uncertainty")
    if values and not all(("action" in value.lower() or "unclear from available data" in value.lower()) for value in values):
        issues.append("each answer must include action or uncertainty")
    if not state.get("win") and state.get("above_avg", "none") != "none":
        above_names = [part.split("(", 1)[0].strip().lower() for part in state.get("above_avg", "").split(",")]
        criticized_above = [name for name in above_names if name and mentions_critically(text, name)]
        if criticized_above and state.get("below_avg", "none") != "none":
            issues.append("may critique an above-average metric")
    return not issues, "; ".join(issues)


def _parse_stripped_participant(match: dict, participant_index: int) -> dict:
    """data/sample_matches.json ships privacy-stripped participants (no puuid,
    perks, or items — see utils/rag.py's build_behavior_narrative for the same
    constraint). Compute the same stats parse_match() would, directly from the
    fields that survive stripping."""
    p = match["info"]["participants"][participant_index]
    team = [pp for pp in match["info"]["participants"] if pp["teamId"] == p["teamId"]]
    team_kills = sum(pp["kills"] for pp in team)
    team_damage = sum(pp["totalDamageDealtToChampions"] for pp in team)
    duration = match["info"]["gameDuration"] / 60
    cs = p["totalMinionsKilled"] + p.get("neutralMinionsKilled", 0)
    return {
        "match_id": match["metadata"]["matchId"],
        "champion": p["championName"],
        "position": p.get("teamPosition", "UNKNOWN"),
        "win": p["win"],
        "kills": p["kills"], "deaths": p["deaths"], "assists": p["assists"],
        "kda": round((p["kills"] + p["assists"]) / max(p["deaths"], 1), 2),
        "kp": round((p["kills"] + p["assists"]) / max(team_kills, 1) * 100, 1),
        "cs_per_min": round(cs / max(duration, 1), 1),
        "vision": p["visionScore"],
        "damage_share": round(p["totalDamageDealtToChampions"] / max(team_damage, 1) * 100, 1),
        "duration": round(duration, 1),
    }


def build_match_state(match: dict, participant_index: int, pool: list[dict]) -> dict | None:
    from features.player_review.benchmarks import get_position_benchmark

    sel = _parse_stripped_participant(match, participant_index)
    if sel["position"] == "UNKNOWN":
        return None

    chall_avg, _ = get_position_benchmark(pool, sel["champion"], sel["position"])

    above, below = [], []
    for key in HIGHER_IS_BETTER:
        target = chall_avg.get(key)
        if not target:
            continue
        actual = sel.get(key, 0)
        entry = f"{METRIC_LABELS[key]} ({actual:.1f} vs {target:.1f})"
        (above if actual >= target else below).append(entry)
    for key in LOWER_IS_BETTER:
        target = chall_avg.get(key)
        if not target:
            continue
        actual = sel.get(key, 0)
        entry = f"{METRIC_LABELS[key]} ({actual:.1f} vs {target:.1f})"
        (above if actual <= target else below).append(entry)

    match_data = (
        f"Champion: {sel['champion']} ({sel['position']})\n"
        f"Result: {'WIN' if sel['win'] else 'LOSS'}\n"
        f"KDA: {sel['kills']}/{sel['deaths']}/{sel['assists']} ({sel['kda']})\n"
        f"CS/min: {sel['cs_per_min']}\n"
        f"Vision score: {sel['vision']}\n"
        f"Kill participation: {sel['kp']}%\n"
        f"Damage share: {sel['damage_share']}%\n"
        f"Duration: {sel['duration']} min"
    )

    return {
        "match_id": sel["match_id"],
        "champion": sel["champion"],
        "position": sel["position"],
        "win": sel["win"],
        "match_data": match_data,
        "timeline_data": "No timeline data.",
        "above_avg": ", ".join(above) if above else "none listed",
        "below_avg": ", ".join(below) if below else "none listed",
        "labels": COACHING_LABELS,
        "repair_count": 0,
    }


def build_rich_match_state(rec: dict, benchmarks: dict) -> dict | None:
    """Build coaching state from the FULL dataset's `challenges` block.

    Same shape as build_match_state(), but match_data now carries the
    lane-phase facts the stripped demo set lacks (CS@10, CS advantage over the
    lane opponent, gold/XP lead, plates, solo kills). Isolates the question:
    how much of the 'generic report' problem is missing input data rather than
    model capability?
    """
    p, ch = rec["participant"], rec["challenges"]
    duration = rec["game_duration"] / 60
    if duration < 5 or not p.get("teamPosition"):
        return None

    team_kills = sum(t.get("kills", 0) or 0 for t in rec["team"]) or 1
    team_damage = sum(t.get("totalDamageDealtToChampions", 0) or 0 for t in rec["team"]) or 1
    cs = (p.get("totalMinionsKilled") or 0) + (p.get("neutralMinionsKilled") or 0)
    sel = {
        "match_id": rec["match_id"],
        "champion": p["championName"],
        "position": p["teamPosition"],
        "win": bool(p["win"]),
        "kills": p["kills"], "deaths": p["deaths"], "assists": p["assists"],
        "kda": round((p["kills"] + p["assists"]) / max(p["deaths"], 1), 2),
        "kp": round((p["kills"] + p["assists"]) / team_kills * 100, 1),
        "cs_per_min": round(cs / max(duration, 1), 1),
        "vision": p["visionScore"],
        "damage_share": round((p["totalDamageDealtToChampions"] or 0) / team_damage * 100, 1),
        "duration": round(duration, 1),
    }

    above, below = [], []
    for key in HIGHER_IS_BETTER:
        target = benchmarks.get(key)
        if not target:
            continue
        entry = f"{METRIC_LABELS[key]} ({sel[key]:.1f} vs {target:.1f})"
        (above if sel[key] >= target else below).append(entry)
    for key in LOWER_IS_BETTER:
        target = benchmarks.get(key)
        if not target:
            continue
        entry = f"{METRIC_LABELS[key]} ({sel[key]:.1f} vs {target:.1f})"
        (above if sel[key] <= target else below).append(entry)

    # The part the stripped dataset cannot provide.
    lane_lines = []
    if ch.get("laneMinionsFirst10Minutes") is not None:
        lane_lines.append(f"CS at minute 10: {ch['laneMinionsFirst10Minutes']}")
    if ch.get("maxCsAdvantageOnLaneOpponent") is not None:
        lane_lines.append(f"Peak CS lead over lane opponent: {ch['maxCsAdvantageOnLaneOpponent']:+.0f}")
    if ch.get("laningPhaseGoldExpAdvantage") is not None:
        lane_lines.append(f"Laning phase gold/XP advantage: {ch['laningPhaseGoldExpAdvantage']}")
    if ch.get("maxLevelLeadLaneOpponent") is not None:
        lane_lines.append(f"Peak level lead: {ch['maxLevelLeadLaneOpponent']}")
    if ch.get("turretPlatesTaken") is not None:
        lane_lines.append(f"Turret plates taken: {ch['turretPlatesTaken']}")
    if ch.get("soloKills") is not None:
        lane_lines.append(f"Solo kills: {ch['soloKills']}")
    if ch.get("killsNearEnemyTurret") is not None:
        lane_lines.append(f"Kills under enemy turret: {ch['killsNearEnemyTurret']}")
    obj_lines = []
    for label, key in (("Dragons", "dragonTakedowns"), ("Heralds", "riftHeraldTakedowns"), ("Barons", "baronTakedowns")):
        if ch.get(key) is not None:
            obj_lines.append(f"{label} participated in: {ch[key]}")
    if ch.get("controlWardsPlaced") is not None:
        obj_lines.append(f"Control wards placed: {ch['controlWardsPlaced']}")
    if ch.get("wardTakedowns") is not None:
        obj_lines.append(f"Enemy wards cleared: {ch['wardTakedowns']}")

    match_data = (
        f"Champion: {sel['champion']} ({sel['position']})\n"
        f"Result: {'WIN' if sel['win'] else 'LOSS'}\n"
        f"KDA: {sel['kills']}/{sel['deaths']}/{sel['assists']} ({sel['kda']})\n"
        f"CS/min: {sel['cs_per_min']}\n"
        f"Vision score: {sel['vision']}\n"
        f"Kill participation: {sel['kp']}%\n"
        f"Damage share: {sel['damage_share']}%\n"
        f"Duration: {sel['duration']} min\n"
        + ("\nLANE PHASE:\n" + "\n".join(lane_lines) if lane_lines else "")
        + ("\nOBJECTIVES & VISION:\n" + "\n".join(obj_lines) if obj_lines else "")
    )

    return {
        "match_id": sel["match_id"], "champion": sel["champion"],
        "position": sel["position"], "win": sel["win"],
        "match_data": match_data,
        "timeline_data": "\n".join(lane_lines) or "No timeline data.",
        "above_avg": ", ".join(above) if above else "none listed",
        "below_avg": ", ".join(below) if below else "none listed",
        "labels": COACHING_LABELS, "repair_count": 0,
    }


def run_one(state: dict) -> dict:
    t0 = time.perf_counter()
    state.update(_build_coaching_context(state))
    state.update(_draft_coaching_report(state))
    t_draft = time.perf_counter() - t0
    draft = state["draft"]

    result = {
        "match_id": state["match_id"],
        "champion": state["champion"],
        "position": state["position"],
        "win": state["win"],
        "above_avg": state["above_avg"],
        "below_avg": state["below_avg"],
        "draft": draft,
        "draft_contradictions": len(check_contradiction(draft, state["above_avg"], state["below_avg"])),
        "has_number": has_number(draft),
        "word_count": len(draft.split()),
        "latency_draft": round(t_draft, 2),
        # Content quality: does this read as advice about THIS match?
        "match_anchors": count_match_anchors(draft, state["match_data"], state["champion"]),
        "template_leaks": len(find_template_leaks(draft)),
        "role_nonsense": len(find_role_nonsense(draft, state["position"])),
        "content_issues": check_content_quality(
            draft, state["match_data"], state["position"], state["champion"]
        ),
        # Actionability: can the player DO something with this next game?
        "actions": [score_action(a) for a in extract_actions(draft)],
        "actionability_issues": check_actionability(draft),
        "configs": {},
    }

    for config_name, judge_fn in (("baseline", judge_coaching_output_legacy), ("v2", judge_coaching_output_v2)):
        passed_first, feedback = judge_fn(state)
        repaired = False
        final_text = draft
        t_repair = 0.0
        if not passed_first:
            t0 = time.perf_counter()
            repaired_text = _clean_output(_llm(STRATEGIC_REPAIR_PROMPT.format(
                feedback=feedback or "failed validation",
                labels="\n".join(f"{label}:" for label in state["labels"]),
                text=draft,
                match_data=state["match_data"][:MAX_CONTEXT_CHARS],
                above_avg=state["above_avg"],
                below_avg=state["below_avg"],
            )))
            t_repair = time.perf_counter() - t0
            repaired = True
            if not repaired_text.startswith("LLM unavailable"):
                final_text = repaired_text
            passed_final, _ = judge_fn({**state, "draft": final_text})
        else:
            passed_final = True

        # Mirrors the finalize-step safety net: if the text still fails
        # validation after the one repair attempt, ship the deterministic
        # fallback instead of a known-bad draft. This is the fix under test —
        # compare shipped_contradictions here against final_contradictions
        # (pre-gate) to see how much of the gap it closes.
        if passed_final:
            shipped_text = final_text
        else:
            shipped_text = _strategic_fallback(
                bool(state.get("win")), state.get("champion", ""),
                state["above_avg"], state["below_avg"],
            )

        result["configs"][config_name] = {
            "passed_first": passed_first,
            "feedback": feedback,
            "repaired": repaired,
            "passed_final": passed_final,
            "final_contradictions": len(check_contradiction(final_text, state["above_avg"], state["below_avg"])),
            "shipped_contradictions": len(check_contradiction(shipped_text, state["above_avg"], state["below_avg"])),
            "fell_back_to_template": not passed_final,
            "latency_repair": round(t_repair, 2),
        }

    return result


def summarize(results: list[dict]) -> dict:
    n = len(results)
    summary = {"n_matches": n, "draft_contradiction_rate": sum(1 for r in results if r["draft_contradictions"] > 0) / n}
    for config in ("baseline", "v2"):
        rows = [r["configs"][config] for r in results]
        summary[config] = {
            "reflection_pass_rate_first": sum(r["passed_first"] for r in rows) / n,
            "reflection_pass_rate_final": sum(r["passed_final"] for r in rows) / n,
            "repair_rate": sum(r["repaired"] for r in rows) / n,
            "final_contradiction_rate": sum(1 for r in rows if r["final_contradictions"] > 0) / n,
            "shipped_contradiction_rate": sum(1 for r in rows if r["shipped_contradictions"] > 0) / n,
            "fallback_rate": sum(r["fell_back_to_template"] for r in rows) / n,
            "latency_repair_p50": round(median([r["latency_repair"] for r in rows if r["repaired"]] or [0]), 2),
        }
    summary["backend"] = "cloud (gpt-4o-mini)" if api_available() else "local ollama (gemma2:2b)"
    summary["content_quality"] = {
        "pass_rate": sum(1 for r in results if not r["content_issues"]) / n,
        "avg_match_anchors": round(sum(r["match_anchors"] for r in results) / n, 2),
        "template_leak_rate": sum(1 for r in results if r["template_leaks"] > 0) / n,
        "role_nonsense_rate": sum(1 for r in results if r["role_nonsense"] > 0) / n,
        "generic_rate": sum(1 for r in results if any("GENERIC" in i for i in r["content_issues"])) / n,
    }
    all_actions = [a for r in results for a in r["actions"]]
    n_act = len(all_actions) or 1
    summary["actionability"] = {
        "actionable_action_rate": sum(a["actionable"] for a in all_actions) / n_act,
        "vague_opener_rate": sum(a["starts_vague"] for a in all_actions) / n_act,
        "has_target_rate": sum(a["has_target"] for a in all_actions) / n_act,
        "has_trigger_rate": sum(a["has_trigger"] for a in all_actions) / n_act,
        "reports_with_zero_actionable": sum(1 for r in results if not any(a["actionable"] for a in r["actions"])) / n,
        "n_actions": len(all_actions),
    }
    summary["specificity_rate"] = sum(r["has_number"] for r in results) / n
    summary["avg_word_count"] = round(sum(r["word_count"] for r in results) / n)
    summary["latency_draft_p50"] = round(median([r["latency_draft"] for r in results]), 2)
    return summary


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rich", action="store_true",
                    help="use the full dataset's challenges block (lane-phase facts)")
    ap.add_argument("--out", default=None, help="results filename stem")
    args = ap.parse_args()

    if args.rich:
        return main_rich(args.out or "rich")

    with (ROOT / "data" / "sample_matches.json").open() as f:
        pool = json.load(f)
    with (ROOT / "evals" / "eval_matches.json").open() as f:
        picks = json.load(f)

    results = []
    for i, pick in enumerate(picks):
        match = pool[pick["match_index"]]
        state = build_match_state(match, pick["participant_index"], pool)
        if not state:
            print(f"  [{i+1}/{len(picks)}] SKIP {pick['match_id']} (no matching participant)")
            continue
        print(f"  [{i+1}/{len(picks)}] {state['champion']:<12} {state['position']:<8} "
              f"{'WIN' if state['win'] else 'LOSS'} ...", flush=True)
        results.append(run_one(state))

    summary = summarize(results)
    out_dir = ROOT / "evals" / "results"
    out_dir.mkdir(exist_ok=True)
    with (out_dir / "raw_results.json").open("w") as f:
        json.dump(results, f, indent=2)
    with (out_dir / "summary.json").open("w") as f:
        json.dump(summary, f, indent=2)

    print("\n" + json.dumps(summary, indent=2))
    print(f"\nWrote {out_dir / 'raw_results.json'} and {out_dir / 'summary.json'}")




def main_rich(stem: str) -> None:
    from features.player_review.benchmarks import get_position_benchmark

    with (ROOT / "data" / "sample_matches.json").open() as f:
        pool = json.load(f)
    with (ROOT / "evals" / "eval_matches_rich.json").open() as f:
        records = json.load(f)

    results = []
    for i, rec in enumerate(records):
        p = rec["participant"]
        bench, _ = get_position_benchmark(pool, p["championName"], p["teamPosition"])
        state = build_rich_match_state(rec, bench)
        if not state:
            print(f"  [{i+1}/{len(records)}] SKIP {rec['match_id']}")
            continue
        print(f"  [{i+1}/{len(records)}] {state['champion']:<12} {state['position']:<8} "
              f"{'WIN' if state['win'] else 'LOSS'} ...", flush=True)
        results.append(run_one(state))

    summary = summarize(results)
    summary["dataset"] = "rich (full local challenges block)"
    out_dir = ROOT / "evals" / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"raw_results_{stem}.json").write_text(json.dumps(results, indent=2))
    (out_dir / f"summary_{stem}.json").write_text(json.dumps(summary, indent=2))
    print("\n" + json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
