"""Tests for the analysis Orchestrator (services/routing_service.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.routing_service import Orchestrator


def _row(key, label, score, actual, target, reliable=True):
    return {
        "key": key, "label": label, "score": score, "actual": actual,
        "target": target, "reliable": reliable, "lower": False, "weight": 0.25,
        "delta": actual - target,
    }


TL = {"cs_at_10": 60, "enemy_cs_at_10": 55, "first_death_minute": 8}


def test_reinforce_when_no_gaps():
    rows = [_row("kp", "Kill Participation", 0.95, 70, 60),
            _row("vision", "Vision Control", 0.98, 80, 40)]
    plan = Orchestrator().route(
        scorecard_rows=rows, champion="Ahri", position="MIDDLE",
        win=True, timeline=TL,
    )
    assert plan.mode == "reinforce"
    assert "reinforcement" in plan.rationale.lower()
    assert plan.primary_gap is None


def test_early_death_routes_to_deep_timeline():
    rows = [_row("deaths_pre_15", "Lane Survival", 0.2, 4, 1.2),
            _row("vision", "Vision Control", 0.9, 45, 40)]
    plan = Orchestrator().route(
        scorecard_rows=rows, champion="Zed", position="MIDDLE",
        win=False, timeline=TL,
    )
    assert plan.mode == "diagnose"
    assert plan.depth.get("timeline") == "deep"
    assert plan.agents[0] == "timeline"
    assert plan.primary_gap.category == "early_death"


def test_itemization_skips_timeline():
    rows = [_row("first_item_min", "Item Timing", 0.3, 18, 13),
            _row("vision", "Vision Control", 0.9, 45, 40)]
    plan = Orchestrator().route(
        scorecard_rows=rows, champion="Jinx", position="BOTTOM",
        win=False, timeline=TL,
    )
    assert plan.mode == "diagnose"
    assert "timeline_deep" in plan.skipped
    assert "item" in plan.agents


def test_missing_timeline_on_laning_gap_is_degraded():
    rows = [_row("cs_diff_10", "Lane CS @10", 0.2, -20, 0)]
    plan = Orchestrator().route(
        scorecard_rows=rows, champion="Darius", position="TOP",
        win=False, timeline=None,
    )
    assert plan.mode == "degraded"
    assert "timeline" in plan.unavailable


def test_three_matches_three_different_plans():
    """Acceptance test from the brief: distinct matches → distinct rationales/agents."""
    m1 = Orchestrator().route(
        scorecard_rows=[_row("deaths_pre_15", "Lane Survival", 0.2, 4, 1.2)],
        champion="Zed", position="MIDDLE", win=False, timeline=TL)
    m2 = Orchestrator().route(
        scorecard_rows=[_row("first_item_min", "Item Timing", 0.3, 18, 13)],
        champion="Jinx", position="BOTTOM", win=False, timeline=TL)
    m3 = Orchestrator().route(
        scorecard_rows=[_row("kp", "Kill Participation", 0.96, 72, 60)],
        champion="Thresh", position="UTILITY", win=True, timeline=TL)

    rationales = {m1.rationale, m2.rationale, m3.rationale}
    agent_sigs = {tuple(m1.agents), tuple(m2.agents), tuple(m3.agents)}
    assert len(rationales) == 3, "rationales must differ across matches"
    assert len(agent_sigs) == 3, "agent lists must differ across matches"


def test_rag_query_is_behavioral_not_statistical():
    rows = [_row("vision", "Vision Control", 0.3, 15, 40)]
    plan = Orchestrator().route(
        scorecard_rows=rows, champion="Lux", position="UTILITY",
        win=False, timeline=TL)
    q = plan.rag_query.lower()
    # Behavioral verbs, not "average vision score"
    assert "vision" in q and ("set up" in q or "deny" in q or "objective" in q)
    assert "average" not in q
