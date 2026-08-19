"""Validation helpers for coaching and counter-guide agent outputs."""
from __future__ import annotations

import re


VAGUE_PHRASES = (
    "play safe",
    "farm well",
    "try to",
    "consider",
    "generally",
    "usually",
    "might",
)

COACHING_LABELS = ("Main Diagnosis", "Lane Phase", "Threat Handling")
COUNTER_LABELS = ("MATCHUP READ", "LANE PLAN", "MID GAME", "LATE GAME", "ITEM PLAN")
AI_COACH_LABELS = (
    "COACH READ",
    "WHAT YOU DID RIGHT",
    "ROLE EXECUTION",
    "TURNING POINTS",
    "PRACTICE ASSIGNMENT",
)


def has_number(text: str) -> bool:
    return bool(re.search(r"\d+\.?\d*", text or ""))


def has_vague_phrase(text: str) -> bool:
    lower = (text or "").lower()
    return any(phrase in lower for phrase in VAGUE_PHRASES)


def mentions_critically(text: str, name: str) -> bool:
    idx = (text or "").lower().find(name.lower())
    if idx == -1:
        return False
    window = text.lower()[max(0, idx - 50) : idx + len(name) + 50]
    neg_words = ("poor", "low", "bad", "weak", "missed", "failed", "lack", "below", "worse", "gap", "not enough", "insufficient", "struggled")
    return any(neg in window for neg in neg_words)


def mentions_positively(text: str, name: str) -> bool:
    idx = (text or "").lower().find(name.lower())
    if idx == -1:
        return False
    window = text.lower()[max(0, idx - 50) : idx + len(name) + 50]
    pos_words = (
        "strong", "great", "good", "solid", "excellent", "advantage", "impressive",
        "well", "high", "above average", "carried", "dominant", "clean",
    )
    return any(pos in window for pos in pos_words)


def _parse_metric_list(metric_str: str) -> list[str]:
    """'vision (97 vs 69.0), roam timing (3.4 vs 2.5)' -> ['vision', 'roam timing']."""
    if not metric_str or metric_str.strip().lower() == "none listed":
        return []
    return [part.split("(", 1)[0].strip().lower() for part in metric_str.split(",") if part.strip()]


def check_contradiction(text: str, above_avg: str, below_avg: str) -> list[str]:
    """
    Directional contradiction check — the single most important validator in the
    system. A confidently wrong coaching tip is worse than no tip, because the
    player will act on it.

    Flags two symmetric failure modes:
      - criticizing a metric that is actually ABOVE the Challenger benchmark
      - praising a metric that is actually BELOW the Challenger benchmark

    ``above_avg``/``below_avg`` are the same comma-separated "name (actual vs
    target)" strings already threaded through the coaching state.
    """
    violations: list[str] = []
    for name in _parse_metric_list(above_avg):
        if name and mentions_critically(text, name):
            violations.append(
                f"CONTRADICTION: '{name}' is ABOVE the Challenger benchmark (a strength) "
                f"but the output criticizes it near that mention — rewrite as a strength."
            )
    for name in _parse_metric_list(below_avg):
        if name and mentions_positively(text, name):
            violations.append(
                f"CONTRADICTION: '{name}' is BELOW the Challenger benchmark (a gap) "
                f"but the output praises it near that mention — do not call a gap a strength."
            )
    return violations


def has_colon_labels(text: str, labels: tuple[str, ...]) -> bool:
    return all(re.search(rf"(^|\n)\s*{re.escape(label)}\s*:", text or "") for label in labels)


def colon_label_values(text: str, labels: tuple[str, ...]) -> list[str]:
    values = []
    for label in labels:
        match = re.search(rf"(^|\n)\s*{re.escape(label)}\s*:\s*(.+)", text or "")
        if match:
            values.append(match.group(2).strip())
    return values


def has_section_headers(text: str, labels: tuple[str, ...]) -> bool:
    return all(re.search(rf"(^|\n)\s*{re.escape(label)}\s*(\n|$)", text or "") for label in labels)


def section_text(text: str, label: str, all_labels: tuple[str, ...]) -> str:
    pattern = rf"(^|\n)\s*{re.escape(label)}\s*(\n|$)"
    match = re.search(pattern, text or "")
    if not match:
        return ""
    start = match.end()
    next_starts = [
        m.start()
        for other in all_labels
        if other != label
        for m in [re.search(rf"\n\s*{re.escape(other)}\s*(\n|$)", text[start:])]
        if m
    ]
    end = start + min(next_starts) if next_starts else len(text)
    return text[start:end].strip()


def judge_coaching_output(state: dict) -> tuple[bool, str]:
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
    match_data = state.get("match_data", "").lower()
    lane_value = colon_label_values(text, ("Lane Phase",))
    if "cs at minute 10: 0" in match_data and lane_value:
        lane_lower = lane_value[0].lower()
        if not any(word in lane_lower for word in ("unreliable", "unclear", "unavailable", "excluded")):
            issues.append("uses suspect CS@10 as lane evidence")
    text_lower = (text or "").lower()
    if any(item in text_lower for item in ("luden", "shadowflame")) and any(word in text_lower for word in ("anti-burst", "survivability", "mitigate burst")):
        issues.append("describes offensive damage items as defensive anti-burst tools")
    issues += check_contradiction(text, state.get("above_avg", ""), state.get("below_avg", ""))
    return not issues, "; ".join(issues)


def judge_counter_output(state: dict) -> tuple[bool, str]:
    text = state.get("draft", "")
    issues = []
    if text.startswith("LLM unavailable"):
        issues.append("local model unavailable")
    if not has_section_headers(text, COUNTER_LABELS):
        issues.append("missing required counter sections")
    if has_vague_phrase(text):
        issues.append("contains generic advice")

    key_items = section_text(text, "ITEM PLAN", COUNTER_LABELS)
    item_lines = [line for line in key_items.splitlines() if line.strip().startswith("-")]
    if len(item_lines) < 2:
        issues.append("needs at least two item recommendations")

    early_plan = section_text(text, "LANE PLAN", COUNTER_LABELS)
    lane_lines = [line for line in early_plan.splitlines() if line.strip().startswith("-")]
    if len(lane_lines) < 2:
        issues.append("lane plan needs at least two bullets")

    mid_plan = section_text(text, "MID GAME", COUNTER_LABELS)
    mid_lines = [line for line in mid_plan.splitlines() if line.strip().startswith("-")]
    if len(mid_lines) < 2:
        issues.append("mid game plan needs at least two bullets")

    timing_text = f"{early_plan}\n{text}".lower()
    if not re.search(r"\b(level|lvl|minute|min|cooldown|spike)\b", timing_text):
        issues.append("needs a level, timing, cooldown, or spike")

    low_value_items = ("doran", "cloak of agility", "long sword", "pickaxe", "recurve bow", "boots")
    if any(item in key_items.lower() for item in low_value_items):
        issues.append("item plan includes starter item or component as final recommendation")

    enemy = state.get("enemy_champ", "").lower()
    if enemy and enemy not in text.lower() and "enemy" not in text.lower():
        issues.append("does not tie advice to the enemy champion")
    return not issues, "; ".join(issues)


def judge_ai_coach_output(state: dict) -> tuple[bool, str]:
    text = state.get("draft", "")
    issues = []
    if text.startswith("LLM unavailable"):
        issues.append("local model unavailable")
    if not has_section_headers(text, AI_COACH_LABELS):
        issues.append("missing required AI coach sections")
    if has_vague_phrase(text):
        issues.append("contains vague coaching language")
    if not has_number(text):
        issues.append("missing concrete match evidence")
    turning_points = section_text(text, "TURNING POINTS", AI_COACH_LABELS).lower()
    if turning_points and not all(word in turning_points for word in ("what", "why", "checklist")):
        issues.append("turning points need what happened, why it mattered, and replay checklist")
    if turning_points and "hypothesis" not in turning_points and "verify" not in turning_points:
        issues.append("turning points need a hypothesis to verify in replay")
    assignment = section_text(text, "PRACTICE ASSIGNMENT", AI_COACH_LABELS).lower()
    if assignment and not any(token in assignment for token in ("target", "pass/fail", "checklist", "before", "@", "+")):
        issues.append("practice assignment needs a measurable target or pass/fail trigger")

    text_lower = text.lower()
    if "several areas" in text_lower and "primary" not in text_lower:
        issues.append("must state the primary failure before broad multi-gap language")
    context_lower = (state.get("coach_context", "") + "\n" + state.get("match_data", "")).lower()
    if "cs@10" in text_lower and any(flag in context_lower for flag in ("cs@10 reads as 0", "excluded from lane diagnosis", "unreliable")):
        if "unreliable" not in text_lower and "excluded" not in text_lower:
            issues.append("uses unreliable CS@10 without caveat")
    if "high kp" in text_lower and "loss" in context_lower and "low-quality" not in text_lower and "not automatically" not in text_lower:
        issues.append("may overpraise high KP in a loss")
    if "split" in text_lower and "side pressure:" in context_lower and "your job" in context_lower:
        if "role" not in text_lower and "job" not in text_lower:
            issues.append("may blur side-lane carrier and reviewed player role")
    if any(item in text_lower for item in ("luden", "shadowflame")) and any(word in text_lower for word in ("anti-burst", "survivability", "mitigate burst")):
        issues.append("describes offensive damage items as defensive anti-burst tools")
    if re.search(r"(failure|weakness)[^.\n]{0,90}above (?:the )?(?:challenger )?average", text_lower):
        issues.append("labels an above-average metric as a failure — contradiction; reinforce instead")
    if "no single primary failure" in context_lower and "primary failure was" in text_lower:
        issues.append("invents a primary failure though coach facts say none exists")
    if "unknown" in turning_points:
        issues.append("turning points built on Unknown timestamps; use known evidence or state timeline unavailable")

    return not issues, "; ".join(issues)


# ─── Content-quality checks ───────────────────────────────────────────────────
# Format checks answer "does this look like coaching?". These answer the harder
# question: "would a real LoL player recognise this as advice about THEIR game?"
# A report can pass every format check and still be generic filler — these
# catch that class of failure.

# Scaffolding from the prompt that must never survive into the output. When the
# model copies the instruction instead of answering it, the report is dead on
# arrival regardless of how well-formed it looks.
TEMPLATE_LEAK_PATTERNS = (
    r"or say unclear from available data",
    r"\[[^\]]{6,}\]",                      # unfilled [one real metric ...] slots
    r"<[^>]{6,}>",                         # unfilled <WHEN-trigger + ...> slots
    r"cs@10,\s*gold@10,\s*deaths,\s*cs/min",
    r"enemy threat names,\s*deaths,\s*items,\s*vision",
    r"one concrete next-game action",
    r"request additional data",            # telling the user to go fetch data
)

# Advice that contradicts what the role is actually judged on. Mirrors the
# position metric weights in services/execution_service.py.
ROLE_NONSENSE = {
    "UTILITY": (
        (r"\b(last hitting|last-hitting|farm efficiency|farming efficiency|cs efficiency)\b",
         "tells a support to focus on last hitting / farm efficiency"),
        (r"\bfocus on (?:consistent )?(?:cs|creep|minion)\b",
         "grades a support on minion CS"),
    ),
    "JUNGLE": (
        (r"\b(?:improve|focus on) (?:your )?lane (?:phase|cs|trading)\b",
         "grades a jungler on solo-lane laning"),
    ),
}


def find_template_leaks(text: str) -> list[str]:
    """Prompt scaffolding that leaked into the output verbatim."""
    lower = (text or "").lower()
    hits = []
    for pattern in TEMPLATE_LEAK_PATTERNS:
        match = re.search(pattern, lower)
        if match:
            hits.append(f"TEMPLATE LEAK: output contains prompt scaffolding {match.group(0)[:60]!r}")
    return hits


def find_role_nonsense(text: str, position: str) -> list[str]:
    """Advice that a player of this role would immediately reject."""
    lower = (text or "").lower()
    hits = []
    for pattern, why in ROLE_NONSENSE.get((position or "").upper(), ()):
        if re.search(pattern, lower):
            hits.append(f"ROLE NONSENSE: {why}")
    return hits


def count_match_anchors(text: str, match_data: str, champion: str = "") -> int:
    """
    How many facts specific to THIS match does the report actually cite?

    Counts the champion name plus every number in the report that genuinely
    appears in the match data. A report scoring 0 would read identically for a
    different game — the definition of generic filler. This is a much stronger
    signal than has_number(), which any hallucinated digit satisfies.
    """
    text = text or ""
    anchors = 0
    if champion and champion.lower() in text.lower():
        anchors += 1

    source_numbers = set(re.findall(r"\d+\.?\d*", match_data or ""))
    for token in set(re.findall(r"\d+\.?\d*", text)):
        if token in source_numbers:
            anchors += 1
    return anchors


def check_content_quality(
    text: str, match_data: str, position: str = "", champion: str = "", min_anchors: int = 2
) -> list[str]:
    """Aggregate content-quality gate: leaks, role nonsense, and genericness."""
    issues = find_template_leaks(text)
    issues += find_role_nonsense(text, position)
    anchors = count_match_anchors(text, match_data, champion)
    if anchors < min_anchors:
        issues.append(
            f"GENERIC: report cites only {anchors} fact(s) from this match "
            f"(need {min_anchors}) — it would read the same for a different game"
        )
    return issues


# ─── Actionability ────────────────────────────────────────────────────────────
# The last gap between "grounded in real data" and "a player knows what to do
# next game". "Focus on positioning" is data-adjacent and completely unusable:
# the player already knows they should position well. An action is only usable
# if it names a trigger (when to do it) and a target (how to tell if you did).

# Openers that signal an abstract intention rather than a behaviour.
VAGUE_ACTION_STEMS = (
    "focus on", "work on", "prioritize", "improve", "be more", "be aware",
    "pay attention", "make sure", "look for opportunities", "keep up",
    "maintain", "continue to", "ensure to", "try", "aim to be",
)

# A concrete trigger: when, or in response to what, the behaviour fires.
TRIGGER_PATTERNS = (
    r"\bbefore\b", r"\bafter\b", r"\bwhen\b", r"\bwhenever\b", r"\bat \d",
    r"\bby (?:the )?\d", r"\bevery\b", r"\bon (?:each|every)\b",
    r"\bminute\b", r"\bmin\b", r"\bspawn", r"\brecall", r"\bback\b",
    r"\blevel \d", r"\bfirst\b", r"\bif\b",
)

# A measurable target: a number the player can check afterwards. Kept
# deliberately broad — an under-matching pattern silently under-reports
# actionability, which is worse than the occasional false positive.
TARGET_PATTERNS = (
    # number + countable game noun, allowing up to two words in between
    # ("2 control wards", "30 jungle CS", "4 turret plates")
    r"\d+(?:\.\d+)?\s*(?:\w+\s+){0,2}(?:cs|kills?|deaths?|wards?|plates?|minions?|camps?|objectives?|dragons?)\b",
    r"\d+(?:\.\d+)?\s*(?:g|gold)\b",          # "1300g"
    r"\d+:\d{2}",                                # "12:00"
    r"\d+(?:\.\d+)?\s*%",                      # "80%"
    r"\d+(?:\.\d+)?\s*/\s*min",                # "5 CS/min"
    r"\b(?:at least|under|below|no more than|fewer than|at most|within)\s+\d",
    r"\d+\s*(?:or fewer|or less|or more|or higher|or better)\b",
    r"\b(?:target|targeting|aim(?:ing)? for|goal of)\s+(?:\w+\s+){0,2}\d",
    r"\d+\s*(?:per|each)\b",
)


def _has_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def score_action(action: str) -> dict:
    """Grade one Action line for whether a player could actually execute it."""
    text = (action or "").strip()
    lower = text.lower()
    starts_vague = any(lower.startswith(stem) for stem in VAGUE_ACTION_STEMS)
    has_trigger = _has_any(text, TRIGGER_PATTERNS)
    has_target = _has_any(text, TARGET_PATTERNS)
    # Usable = tells you WHEN to do it and HOW to check you did it.
    actionable = has_trigger and has_target
    return {
        "text": text,
        "starts_vague": starts_vague,
        "has_trigger": has_trigger,
        "has_target": has_target,
        "actionable": actionable,
    }


def extract_actions(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"Action:\s*([^\n]+)", text or "")]


def check_actionability(text: str, min_actionable: int = 1) -> list[str]:
    """Require at least one Action a player could actually execute next game."""
    actions = extract_actions(text)
    if not actions:
        return []
    scored = [score_action(a) for a in actions]
    if sum(s["actionable"] for s in scored) >= min_actionable:
        return []
    worst = next((s for s in scored if s["starts_vague"]), scored[0])
    missing = []
    if not worst["has_trigger"]:
        missing.append("a trigger (when to do it: before dragon, on each recall, by minute 10)")
    if not worst["has_target"]:
        missing.append("a measurable target (2 control wards, under 3 deaths, 5 CS/min)")
    return [
        f"NOT ACTIONABLE: no Action tells the player what to actually do next game. "
        f"e.g. {worst['text'][:70]!r} needs " + " and ".join(missing)
    ]
