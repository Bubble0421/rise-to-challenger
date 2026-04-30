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
    neg_words = ("poor", "low", "bad", "weak", "missed", "failed", "lacking", "below", "worse", "gap", "not enough")
    return any(neg in window for neg in neg_words)


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
    if not state.get("win") and state.get("above_avg", "none") != "none":
        above_names = [part.split("(", 1)[0].strip().lower() for part in state.get("above_avg", "").split(",")]
        criticized_above = [name for name in above_names if name and mentions_critically(text, name)]
        if criticized_above and state.get("below_avg", "none") != "none":
            issues.append("may critique an above-average metric")
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

    return not issues, "; ".join(issues)
