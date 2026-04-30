"""
Position-specific execution scorecard — rule-based scoring, no LLM.
Targets are computed from actual Challenger data, not hardcoded.
"""
from __future__ import annotations

# ─── Position metric definitions ──────────────────────────────────────────────

POSITION_METRICS: dict[str, list[dict]] = {
    "UTILITY": [
        {"key": "vision",      "label": "Vision Control",     "weight": 0.30, "lower_is_better": False},
        {"key": "kp",          "label": "Kill Participation",  "weight": 0.30, "lower_is_better": False},
        {"key": "deaths",      "label": "Survival",            "weight": 0.20, "lower_is_better": True},
        {"key": "roam_count",  "label": "Roam Timing",         "weight": 0.20, "lower_is_better": False},
    ],
    "JUNGLE": [
        {"key": "kp",          "label": "Gank Impact",         "weight": 0.35, "lower_is_better": False},
        {"key": "vision",      "label": "Vision Control",      "weight": 0.25, "lower_is_better": False},
        {"key": "cs_per_min",  "label": "Farm Efficiency",     "weight": 0.20, "lower_is_better": False},
        {"key": "deaths",      "label": "Survival",            "weight": 0.20, "lower_is_better": True},
    ],
    "MIDDLE": [
        {"key": "cs_diff_10",  "label": "Lane CS @10",         "weight": 0.25, "lower_is_better": False},
        {"key": "kp",          "label": "Roam Impact",         "weight": 0.35, "lower_is_better": False},
        {"key": "vision",      "label": "River Vision",        "weight": 0.20, "lower_is_better": False},
        {"key": "deaths",      "label": "Survival",            "weight": 0.20, "lower_is_better": True},
    ],
    "TOP": [
        {"key": "cs_diff_10",       "label": "Lane CS @10",   "weight": 0.30, "lower_is_better": False},
        {"key": "deaths",           "label": "Survival",       "weight": 0.25, "lower_is_better": True},
        {"key": "damage_share",     "label": "Teamfight Impact","weight": 0.25, "lower_is_better": False},
        {"key": "vision",           "label": "Vision Control", "weight": 0.20, "lower_is_better": False},
    ],
    "BOTTOM": [
        {"key": "cs_diff_10",       "label": "Lane CS @10",    "weight": 0.30, "lower_is_better": False},
        {"key": "deaths_pre_15",    "label": "Lane Survival",  "weight": 0.25, "lower_is_better": True},
        {"key": "first_item_min",   "label": "Item Timing",    "weight": 0.25, "lower_is_better": True},
        {"key": "damage_share",     "label": "Teamfight Impact","weight": 0.20, "lower_is_better": False},
    ],
}

# ─── Target computation from Challenger data ───────────────────────────────────

def compute_chall_targets(
    matches: list[dict],
    position: str,
    champion: str,
    chall_avg: dict,
) -> dict[str, float]:
    """
    Derive per-position target values from the actual Challenger dataset.
    Falls back to sensible defaults if data is sparse.
    """
    # Start with known Challenger averages from get_position_benchmark
    targets = {
        "vision":         max(chall_avg.get("vision", 40.0), 1.0),
        "kp":             chall_avg.get("kp", 55.0),
        "deaths":         chall_avg.get("deaths", 3.5),
        "cs_per_min":     chall_avg.get("cs_per_min", 7.0),
        "damage_share":   chall_avg.get("damage_share", 22.0),
        # Timeline-derived (fallback estimates)
        "cs_diff_10":     0.0,     # Challenger avg CS diff is ~0 (symmetric)
        "deaths_pre_15":  1.2,     # Challenger avg early deaths
        "first_item_min": 13.0,    # Challenger avg first legendary
        "roam_count":     2.5 if position == "UTILITY" else 3.0,
    }
    return targets


# ─── Scorecard computation ─────────────────────────────────────────────────────

def _clamp_score(score: float) -> float:
    return max(0.0, min(1.0, score))


def compute_scorecard(
    player_data: dict,
    targets: dict[str, float],
    timeline_data: dict | None,
    position: str,
) -> list[dict]:
    """
    Return a list of metric rows for the scorecard table.
    Each row: {key, label, weight, target, actual, score, result, delta}
    """
    metrics = POSITION_METRICS.get(position, POSITION_METRICS["MIDDLE"])
    tl = timeline_data or {}

    # Augment player_data with timeline-derived metrics
    augmented = dict(player_data)
    cs10 = tl.get("cs_at_10") if tl else None
    enemy_cs10 = tl.get("enemy_cs_at_10") if tl else None
    lane_cs_valid = isinstance(cs10, int) and isinstance(enemy_cs10, int)
    if lane_cs_valid and position != "UTILITY" and cs10 == 0 and player_data.get("cs", 0) >= 25:
        lane_cs_valid = False
    augmented["cs_diff_10"] = (cs10 - enemy_cs10) if lane_cs_valid else None
    augmented["deaths_pre_15"] = tl.get("deaths_pre_15", player_data.get("deaths", 0)) if tl else None
    augmented["first_item_min"] = tl.get("first_item_minute") if tl else None
    augmented["roam_count"] = tl.get("roam_count", player_data.get("kp", 0) / 20)

    rows = []
    for m in metrics:
        key   = m["key"]
        label = m["label"]
        lower = m["lower_is_better"]
        tgt   = targets.get(key, 0.0)
        actual = augmented.get(key, 0.0)
        reliable = actual is not None

        if not reliable:
            score = 0.5
        elif tgt == 0:
            score = 0.5
        elif lower:
            # Lower is better: perfect = actual <= tgt, terrible = actual >= 2*tgt
            score = _clamp_score(1.0 - (actual - tgt) / max(tgt, 1))
        else:
            score = _clamp_score(actual / max(tgt, 0.01))

        # Result label
        if not reliable:
            result = "Unavailable"
        elif score >= 0.85:
            result = "Excellent"
        elif score >= 0.65:
            result = "Average"
        else:
            result = "Below"

        delta = (actual - tgt) if reliable else 0.0

        rows.append({
            "key":    key,
            "label":  label,
            "weight": m["weight"],
            "lower":  lower,
            "target": tgt,
            "actual": actual if reliable else 0.0,
            "score":  score,
            "result": result,
            "delta":  delta,
            "reliable": reliable,
        })

    return rows


def compute_grade(rows: list[dict]) -> tuple[str, str]:
    """
    Weighted score → letter grade + one-line explanation.
    Returns ("B+", "explanation text")
    """
    reliable_rows = [r for r in rows if r.get("reliable", True)]
    if reliable_rows:
        reliable_weight = sum(r["weight"] for r in reliable_rows)
        weighted = sum(r["score"] * r["weight"] for r in reliable_rows) / max(reliable_weight, 0.01)
    else:
        weighted = 0.5

    if weighted >= 0.92:
        grade, desc = "S", "Exceptional — Challenger-level execution."
    elif weighted >= 0.82:
        grade, desc = "A", "Strong performance with minor gaps."
    elif weighted >= 0.72:
        grade, desc = "B+", "Solid fundamentals, one key area to fix."
    elif weighted >= 0.62:
        grade, desc = "B", "Decent game with clear improvement areas."
    elif weighted >= 0.52:
        grade, desc = "C+", "Several gaps — strategic decisions cost impact."
    elif weighted >= 0.42:
        grade, desc = "C", "Below average — multiple execution failures."
    else:
        grade, desc = "D", "Core fundamentals need significant work."

    # Override description with the biggest failure
    worst = min(reliable_rows or rows, key=lambda r: r["score"])
    if worst["score"] < 0.5:
        desc = f"{worst['label']} was the primary failure this game."

    return grade, desc


def get_top_gaps(rows: list[dict], n: int = 3) -> list[dict]:
    """Return the n worst-scoring metrics (gaps to address)."""
    reliable_rows = [r for r in rows if r.get("reliable", True)]
    return sorted(reliable_rows or rows, key=lambda r: r["score"])[:n]
