from services.execution_service import compute_grade, compute_scorecard


def test_scorecard_handles_lower_is_better_metric():
    rows = compute_scorecard(
        player_data={"deaths": 2, "kp": 60, "vision": 30, "cs_per_min": 7},
        targets={"deaths": 4, "kp": 50, "vision": 25, "cs_per_min": 7},
        timeline_data=None,
        position="JUNGLE",
    )

    deaths = next(row for row in rows if row["key"] == "deaths")
    assert deaths["score"] == 1.0
    assert deaths["result"] == "Excellent"


def test_compute_grade_uses_weighted_rows():
    grade, desc = compute_grade([
        {"score": 0.95, "weight": 0.5, "label": "A"},
        {"score": 0.90, "weight": 0.5, "label": "B"},
    ])

    assert grade == "S"
    assert "Exceptional" in desc
