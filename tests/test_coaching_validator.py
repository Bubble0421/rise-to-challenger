from features.coaching.validators import check_contradiction, judge_coaching_output


def test_coaching_validator_requires_diagnostic_labels_and_grounding():
    text = (
        "Main Diagnosis: Evidence: Vision 80 vs avg 60. Meaning: fog setup was a strength. Action: repeat river setup before objective spawn.\n"
        "Lane Phase: Evidence: CS@10 62 vs enemy 70. Meaning: wave control lagged. Action: stabilize wave before roaming.\n"
        "Threat Handling: Evidence: enemy Akali present. Meaning: flank threat changes spell usage. Action: hold Q for flank pressure."
    )

    passed, feedback = judge_coaching_output({"draft": text, "labels": ("Main Diagnosis", "Lane Phase", "Threat Handling")})

    assert passed, feedback


def test_check_contradiction_catches_criticizing_a_strength():
    # The Seraphine example: vision is a real strength (134 vs 72.5) but the
    # output criticizes it anyway.
    text = "Seraphine's lack of early vision control led to the gold deficit."
    violations = check_contradiction(text, above_avg="vision (134 vs 72.5)", below_avg="none listed")
    assert violations
    assert "vision" in violations[0].lower()


def test_check_contradiction_catches_praising_a_weakness():
    text = "Your strong kill participation carried this game."
    violations = check_contradiction(text, above_avg="none listed", below_avg="kill participation (38 vs 60)")
    assert violations
    assert "kill participation" in violations[0].lower()


def test_check_contradiction_allows_correctly_directed_feedback():
    text = "Vision was a clear strength at 134 vs the 72.5 benchmark. Kill participation lagged at 38% vs 60%."
    violations = check_contradiction(
        text, above_avg="vision (134 vs 72.5)", below_avg="kill participation (38 vs 60)"
    )
    assert violations == []


def test_check_contradiction_no_metrics_no_violations():
    assert check_contradiction("Generic text with no metric mentions.", "none listed", "none listed") == []


# ─── Content-quality checks ───────────────────────────────────────────────────

from features.coaching.validators import (
    check_content_quality,
    count_match_anchors,
    find_role_nonsense,
    find_template_leaks,
)

MATCH_DATA = (
    "Champion: Karma (UTILITY)\nResult: WIN\nKDA: 4/6/20 (4.0)\n"
    "CS/min: 0.9\nVision score: 67.0\nKill participation: 63.2%\n"
)


def test_template_leak_detected():
    # Real observed failure: the model copied the prompt's instruction text
    # instead of answering it.
    text = "Lane Phase: Evidence: CS@10, gold@10, deaths, CS/min, or say unclear from available data."
    leaks = find_template_leaks(text)
    assert leaks
    assert any("TEMPLATE LEAK" in leak for leak in leaks)


def test_unfilled_bracket_placeholder_detected():
    assert find_template_leaks("Main Diagnosis: Evidence: [one real metric or comp fact].")


def test_role_nonsense_support_told_to_farm():
    text = "Action: Focus on consistent last hitting and farm efficiency."
    issues = find_role_nonsense(text, "UTILITY")
    assert issues and "support" in issues[0].lower()


def test_role_nonsense_not_flagged_for_farming_roles():
    text = "Action: Focus on consistent last hitting and farm efficiency."
    assert find_role_nonsense(text, "MIDDLE") == []


def test_count_match_anchors_only_counts_real_numbers():
    # 67.0 and 0.9 are real; 999 is hallucinated and must not count.
    text = "Vision 67.0 and CS/min 0.9 held up, but 999 is invented."
    assert count_match_anchors(text, MATCH_DATA, "Karma") == 2  # 67.0, 0.9 (no champ name in text)


def test_count_match_anchors_counts_champion_name():
    text = "Karma held vision at 67.0."
    assert count_match_anchors(text, MATCH_DATA, "Karma") == 2  # champion + 67.0


def test_generic_report_is_flagged():
    text = "Focus on maximizing impact in teamfights and securing objectives with your team."
    issues = check_content_quality(text, MATCH_DATA, "UTILITY", "Karma")
    assert any("GENERIC" in i for i in issues)


def test_specific_report_passes_content_quality():
    text = "Karma's vision score 67.0 trailed the benchmark; ward the pit before the 63.2% fight window."
    assert check_content_quality(text, MATCH_DATA, "UTILITY", "Karma") == []


# ─── Actionability ────────────────────────────────────────────────────────────

from features.coaching.validators import check_actionability, extract_actions, score_action


def test_vague_action_is_not_actionable():
    # The dominant real-world failure: advice the player already knows.
    s = score_action("Focus on positioning to avoid unnecessary deaths.")
    assert not s["actionable"] and s["starts_vague"]


def test_trigger_without_target_is_not_actionable():
    s = score_action("Prioritize objectives after securing a lead.")
    assert s["has_trigger"] and not s["has_target"] and not s["actionable"]


def test_actionable_needs_trigger_and_target():
    s = score_action("Before minute 10, secure at least 30 CS from jungle camps.")
    assert s["has_trigger"] and s["has_target"] and s["actionable"]


def test_target_detection_handles_real_phrasings():
    # Regression: an earlier pattern set under-matched all of these, silently
    # under-reporting actionability.
    for text in (
        "Recall by minute 10 with 1300g to target first item by 12:00.",
        "After each death, reduce deaths to 4 or fewer next game.",
        "Before each objective spawn, place 2 control wards.",
        "Before the next fight, target 80% kill participation.",
    ):
        assert score_action(text)["has_target"], text


def test_extract_actions_pulls_every_action_line():
    text = "Main Diagnosis: Evidence: x. Action: Before minute 10, get 30 CS.\nLane Phase: Action: Ward by 8:00."
    assert len(extract_actions(text)) == 2


def test_check_actionability_passes_when_one_action_is_usable():
    text = ("Main Diagnosis: Action: Focus on positioning.\n"
            "Lane Phase: Action: Before minute 10, secure at least 30 CS.")
    assert check_actionability(text) == []


def test_check_actionability_flags_all_vague_report():
    text = ("Main Diagnosis: Action: Focus on positioning.\n"
            "Lane Phase: Action: Work on your vision.")
    issues = check_actionability(text)
    assert issues and "NOT ACTIONABLE" in issues[0]
