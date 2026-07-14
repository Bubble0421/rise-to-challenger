"""
Analysis orchestrator — turns a fixed pipeline into a real routing decision.

The old flow ran the same analysis for every match. That is not orchestration;
it is a static function with extra steps. This module scores the player's gaps
(reusing the deterministic execution scorecard as the single source of truth),
then *decides*:

  - what MODE the review is in (diagnose a real gap, reinforce a clean game, or
    run degraded because key data is missing),
  - which analysis paths to DEEPEN and which to SKIP,
  - a human-readable RATIONALE the UI shows the user, and
  - a behavioral RAG QUERY so retrieval looks for *decisions*, not averages.

Every field is derived from this match, so three different matches produce three
visibly different plans. No LLM is involved, so it runs anywhere the app runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# Map scorecard metric keys → the analysis category that owns them.
CATEGORY_MAP: dict[str, str] = {
    "deaths":         "death_control",
    "deaths_pre_15":  "early_death",
    "first_item_min": "itemization",
    "kp":             "participation",
    "roam_count":     "participation",
    "vision":         "vision",
    "cs_per_min":     "lane_farm",
    "cs_diff_10":     "lane_farm",
    "damage_share":   "teamfight",
}

# A gap must be at least this severe (0..1, where severity = 1 - score) before we
# treat the game as "something went wrong". Below it, we reinforce instead.
DIAGNOSE_THRESHOLD = 0.18

# Per-category behavioral RAG intent. The point of the RAG rewrite: retrieve what
# Challenger players *did* in this situation, not the average number.
_BEHAVIOR_INTENT: dict[str, str] = {
    "death_control": "how they limited deaths, respected fog, and recovered tempo after dying",
    "early_death":   "how they survived the laning phase and punished versus getting solo-killed early",
    "itemization":   "the item path and power-spike timing they hit for this matchup",
    "participation": "when they left lane to join fights and how they showed up to objectives",
    "vision":        "how they used vision to set up objectives and deny enemy picks",
    "lane_farm":     "how they built and converted a CS and gold lead in lane",
    "teamfight":     "their teamfight positioning and how they created damage in fights",
}


@dataclass
class Gap:
    metric: str
    category: str
    severity: float      # 0.0-1.0, higher = worse
    value: float
    benchmark: float
    label: str = ""


@dataclass
class RoutingPlan:
    mode: Literal["diagnose", "reinforce", "degraded"]
    agents: list[str]
    skipped: list[str] = field(default_factory=list)
    depth: dict[str, str] = field(default_factory=dict)
    rationale: str = ""                 # human-readable, rendered in the UI
    focus: str = ""                     # short directive fed to the coach LLM
    rag_query: str = ""                 # behavioral retrieval query
    unavailable: list[str] = field(default_factory=list)
    primary_gap: Gap | None = None


class Orchestrator:
    """Routes a match to an analysis plan based on its actual gaps."""

    def route(
        self,
        *,
        scorecard_rows: list[dict],
        champion: str,
        position: str,
        win: bool,
        timeline: dict | None,
        match_data: dict | None = None,
    ) -> RoutingPlan:
        champ = champion or "This champion"
        pos = position or "role"
        match_data = match_data or {}

        unavailable = self._missing_data(timeline, match_data)
        gaps = self._score_gaps(scorecard_rows)

        # ── Branch A: nothing is actually wrong → REINFORCE ─────────────────────
        if not gaps or gaps[0].severity < DIAGNOSE_THRESHOLD:
            return RoutingPlan(
                mode="reinforce",
                agents=["comp", "execution"],
                skipped=["timeline_deep", "item_deep"],
                depth={"timeline": "shallow"},
                rationale=(
                    f"Every tracked metric is at or above the {champ} {pos} Challenger "
                    "benchmark. Switching to reinforcement mode — naming what worked and how "
                    "to repeat it, instead of manufacturing a mistake that isn't there."
                ),
                focus=(
                    "REINFORCE: no benchmark gap dominates. Name the specific winning pattern "
                    "and the exact condition to repeat it. Do not invent a failure."
                ),
                rag_query=self._behavior_query(champ, pos, "teamfight", win=True),
                unavailable=unavailable,
            )

        primary = gaps[0]
        category = primary.category
        timeline_missing = "timeline" in unavailable

        # ── Branch B: an early / laning failure → the timeline IS the story ─────
        if category in {"early_death", "lane_farm"}:
            if timeline_missing:
                return self._degraded(primary, champ, pos, win, unavailable,
                                      reason="the primary gap is a laning-phase problem but no "
                                             "timeline was returned")
            deepen_item = category == "early_death" and self._itemization_secondary(gaps)
            return RoutingPlan(
                mode="diagnose",
                agents=["timeline", "comp", "execution"],
                skipped=[] if deepen_item else ["item_deep"],
                depth={"timeline": "deep"},
                rationale=self._gap_line(primary)
                + " Running deep timeline analysis to trace the gold and tempo consequences"
                + ("" if deepen_item else " — build matched benchmark, so the item deep-dive is skipped.")
                + ("." if deepen_item else ""),
                focus=(
                    f"DIAGNOSE laning: anchor the review on {primary.label.lower()} "
                    f"({primary.value:g} vs benchmark {primary.benchmark:g}). Trace it through "
                    "the timeline — first death, first recall, first river move."
                ),
                rag_query=self._behavior_query(champ, pos, category, win=win),
                unavailable=unavailable,
                primary_gap=primary,
            )

        # ── Branch C: itemization → the timeline is NOT the story ──────────────
        if category == "itemization":
            return RoutingPlan(
                mode="diagnose",
                agents=["comp", "item", "execution"],
                skipped=["timeline_deep"],
                depth={"timeline": "shallow"},
                rationale=self._gap_line(primary)
                + " Lane economy was not the dominant gap, so the timeline is not the story — "
                "running comp-aware itemisation analysis instead.",
                focus=(
                    f"DIAGNOSE itemisation: the build/timing gap ({primary.label.lower()}) is the "
                    "anchor. Judge each item against the enemy win condition, not lane CS."
                ),
                rag_query=self._behavior_query(champ, pos, category, win=win),
                unavailable=unavailable,
                primary_gap=primary,
            )

        # ── Branch D: participation / vision → map movement is the story ───────
        if category in {"participation", "vision"}:
            depth = {"timeline": "shallow" if timeline_missing else "deep"}
            return RoutingPlan(
                mode="diagnose" if not timeline_missing else "degraded",
                agents=["comp", "timeline", "execution"],
                skipped=["item_deep"],
                depth=depth,
                rationale=self._gap_line(primary)
                + " Analysing which fights and objective setups were missed, and where you "
                "were on the map instead."
                + (" Timeline is unavailable, so this runs on box-score evidence only."
                   if timeline_missing else ""),
                focus=(
                    f"DIAGNOSE {category}: anchor on {primary.label.lower()} "
                    f"({primary.value:g} vs benchmark {primary.benchmark:g}). Review timing to "
                    "objectives and presence in fights, not farm."
                ),
                rag_query=self._behavior_query(champ, pos, category, win=win),
                unavailable=unavailable,
                primary_gap=primary,
            )

        # ── Branch E: death control / teamfight / fallback → full analysis ─────
        return RoutingPlan(
            mode="diagnose" if not timeline_missing else "degraded",
            agents=["comp", "timeline", "item", "execution"],
            depth={"timeline": "shallow" if timeline_missing else "deep"},
            rationale=self._gap_line(primary)
            + " No single sub-system dominates, so running the full analysis and letting the "
            "evidence rank the fixes.",
            focus=(
                f"DIAGNOSE: primary gap is {primary.label.lower()} "
                f"({primary.value:g} vs benchmark {primary.benchmark:g}). Keep it as the review anchor."
            ),
            rag_query=self._behavior_query(champ, pos, category, win=win),
            unavailable=unavailable,
            primary_gap=primary,
        )

    # ── Internals ──────────────────────────────────────────────────────────────

    def _score_gaps(self, rows: list[dict]) -> list[Gap]:
        """Turn scorecard rows into ranked gaps. Reuses the scorecard's own score
        (0..1, higher is better) so routing agrees with the grade the user sees."""
        gaps: list[Gap] = []
        for row in rows or []:
            if not row.get("reliable", True):
                continue
            key = row.get("key", "")
            category = CATEGORY_MAP.get(key)
            if category is None:
                continue
            score = row.get("score", 1.0)
            if score >= 1.0:
                continue
            gaps.append(Gap(
                metric=key,
                category=category,
                severity=max(0.0, min(1.0, 1.0 - score)),
                value=float(row.get("actual", 0.0)),
                benchmark=float(row.get("target", 0.0)),
                label=row.get("label", key),
            ))
        return sorted(gaps, key=lambda g: g.severity, reverse=True)

    def _itemization_secondary(self, gaps: list[Gap]) -> bool:
        return any(g.category == "itemization" and g.severity >= DIAGNOSE_THRESHOLD for g in gaps[1:])

    def _missing_data(self, timeline: dict | None, match_data: dict) -> list[str]:
        missing: list[str] = []
        if not timeline:
            missing.append("timeline")
        player = match_data.get("player", match_data) if isinstance(match_data, dict) else {}
        if isinstance(player, dict) and "perks" not in player and "runes" not in player:
            # Runes are optional context; only flag when we were given a player blob at all.
            if player:
                missing.append("runes")
        return missing

    def _gap_line(self, gap: Gap) -> str:
        return (
            f"Primary gap: {gap.label} — {gap.value:g} vs Challenger benchmark {gap.benchmark:g} "
            f"(severity {gap.severity:.0%})."
        )

    def _behavior_query(self, champ: str, pos: str, category: str, *, win: bool) -> str:
        intent = _BEHAVIOR_INTENT.get(category, "the key decisions they made")
        outcome = "in a winning game" if win else "in a losing game they still played well"
        return f"Challenger {champ} {pos} {intent} {outcome}"

    def _degraded(self, primary: Gap, champ: str, pos: str, win: bool,
                  unavailable: list[str], *, reason: str) -> RoutingPlan:
        return RoutingPlan(
            mode="degraded",
            agents=["comp", "execution"],
            skipped=["timeline_deep", "item_deep"],
            depth={"timeline": "unavailable"},
            rationale=self._gap_line(primary)
            + f" Running in degraded mode because {reason}; diagnosis leans on box-score "
            "evidence and asks you to verify the rest in replay.",
            focus=(
                f"DEGRADED: anchor on {primary.label.lower()} but flag that timeline evidence is "
                "missing. Do not assert exact death cause or wave state; ask the player to verify."
            ),
            rag_query=self._behavior_query(champ, pos, primary.category, win=win),
            unavailable=unavailable,
            primary_gap=primary,
        )
