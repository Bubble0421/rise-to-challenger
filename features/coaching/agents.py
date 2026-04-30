"""Data-grounded agent orchestration for the dashboard.

The UI calls three public functions:
- run_strategic_agent() for legacy Player Review coaching cards
- run_ai_coach_report_agent() for the personalized post-game coach report
- run_counter_agents() for Counter Guide matchup advice

Internally each flow is a small LangGraph workflow with bounded reflection:
draft -> validate -> one repair -> final. If LangGraph is unavailable, the same
nodes run sequentially so the app still works.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Callable, Literal, TypedDict

from core.config import OLLAMA_MODEL
from features.coaching.knowledge import build_knowledge_context
from features.coaching.validators import (
    AI_COACH_LABELS,
    COUNTER_LABELS,
    COACHING_LABELS,
    has_colon_labels as _has_colon_labels,
    has_section_headers as _has_section_headers,
    judge_coaching_output as _judge_coaching_output,
    judge_counter_output as _judge_counter_output,
    judge_ai_coach_output as _judge_ai_coach_output,
)
from utils.rag import CHALLENGER_COLLECTION, YOUTUBE_COLLECTION, search_rag
from services.counter_plan_service import build_counter_plan


MAX_CONTEXT_CHARS = 3_500
MAX_REPAIRS = 1


class CoachingState(TypedDict, total=False):
    match_data: str
    timeline_data: str
    champion: str
    position: str
    win: bool
    above_avg: str
    below_avg: str
    knowledge_context: str
    labels: tuple[str, ...]
    draft: str
    final: str
    reflection_feedback: str
    passed_reflection: bool
    repair_count: int


class CounterState(TypedDict, total=False):
    your_champ: str
    your_pos: str
    enemy_champ: str
    matchup_data: str
    matchup_summary: str
    baseline_plan: str
    rag_context: str
    sources: list[str]
    draft: str
    final: str
    reflection_feedback: str
    passed_reflection: bool
    repair_count: int
    status_writer: Callable[[str], None] | None


class AICoachState(TypedDict, total=False):
    coach_context: str
    match_data: str
    timeline_data: str
    champion: str
    position: str
    rag_context: str
    sources: list[str]
    draft: str
    final: str
    reflection_feedback: str
    passed_reflection: bool
    repair_count: int

STRATEGIC_PROMPT = """\
You are a Diamond+ League of Legends positional coach reviewing a ranked match.
The product goal is diagnosis, not generic praise. Use available data first, then translate it into meaning and one concrete action.

RESULT: {result}
ROLE: {position}
CHAMPION: {champion}

Match data:
{match_data}

Timeline data:
{timeline_data}

Metrics above Challenger average: {above_avg}
Metrics below Challenger average: {below_avg}

Injected coaching knowledge:
{knowledge_context}

Output exactly these 3 labeled answers and nothing else:

Main Diagnosis: Evidence: [one real metric, item, enemy champion, or comp fact]. Meaning: [the most important review point: repeat a strength or fix a risk]. Action: [one concrete next-game action].
Lane Phase: Evidence: [CS@10, gold@10, deaths, CS/min, or say unclear from available data]. Meaning: [pressure/stabilize/concede wave/roam diagnosis]. Action: [one lane-specific correction].
Threat Handling: Evidence: [enemy threat names, deaths, items, vision, or say unclear from available data]. Meaning: [what the threat changed about spacing, spell usage, or itemization]. Action: [one specific spell-hold, vision-entry, or itemization correction].

Rules:
- Max 2 short sentences and 56 words per answer.
- Include at least one real number across the output.
- Every answer must include "Evidence:", "Meaning:", and "Action:" unless the data is unavailable; then write "unclear from available data".
- Treat DATA QUALITY as a hard gate: if CS@10/gold/death timing is marked suspect or unavailable, do not diagnose lane from that field.
- If CS@10 is 0 for a farming role, call it unreliable instead of calling the lane lost.
- Separate team identity from player job; do not assign split-push responsibility to a non-side-lane champion just because the team has a split pusher.
- In a loss, high KP with low damage and high deaths may be low-quality fight participation, not a pure strength.
- If most core metrics are below benchmark, do not frame the game as strong fundamentals.
- Do not fabricate skillshot accuracy, ward location, voice comms, brush checks, objective participation, or exact death cause.
- Do not mention dragon/baron as secured unless present in data; talk about objective setup instead.
- Do not describe champions with traits contradicted by injected knowledge.
- Do not recommend offensive damage items as anti-burst or survivability tools.
- Avoid vague phrases: play safe, farm well, try to, consider, generally, usually, might.
"""


STRATEGIC_REPAIR_PROMPT = """\
Previous coaching output failed validation.

Validation feedback:
{feedback}

Required labels:
{labels}

Original output:
{text}

Grounding data:
{match_data}

Above-average metrics: {above_avg}
Below-average metrics: {below_avg}

Rules:
- Preserve useful specifics.
- Remove vague phrases.
- Include at least one number.
- Max 2 short sentences and 56 words per answer.
- Use exactly these labels: Main Diagnosis, Lane Phase, Threat Handling.
- Every answer must include Evidence, Meaning, and Action, or say unclear from available data.
- Respect data-quality notes; do not use CS@10/gold/death timing when marked unreliable.
- Do not call high KP a strength in a loss when damage is low and deaths are high.
- Keep player role separate from another champion's side-lane job.
- Do not fabricate skillshot accuracy, ward location, comms, brush checks, objective participation, or exact death cause.
- Output only the required labeled answers.
"""


COUNTER_DRAFT_PROMPT = """\
You are giving a ranked player a pre-game matchup preview and game plan.

Matchup data:
{matchup_data}

Rule-based baseline plan:
{baseline_plan}

High-elo reference context:
{rag_context}

Output exactly these 5 sections and nothing else:

MATCHUP READ
[One sentence explaining if the matchup is favorable, even, or difficult. Reference a level, ability, or data point.]

LANE PLAN
- [Specific trade or spacing instruction, max 14 words]
- [Specific thing to respect from {enemy_champ}, max 14 words]

MID GAME
- [How {your_champ} should move after lane, max 16 words]
- [What objective or side of map matters most, max 16 words]

LATE GAME
[One sentence for teamfight role: engage, peel, flank, poke, split, or front-to-back.]

ITEM PLAN
- [Item 1] - [short reason tied to {enemy_champ} or enemy comp]
- [Item 2] - [short reason tied to {enemy_champ} or enemy comp]

Rules:
- No intro or outro.
- The rule-based baseline is the product floor; preserve its matchup-specific ideas unless RAG/data clearly improves them.
- Avoid vague phrases: play safe, farm well, try to, consider, generally.
- Name specific abilities, items, or timing windows where possible.
- Treat low sample matchup data as directional, not certain.
- Do not recommend starter items or small components as final item plan unless explicitly discussing first recall.
"""


COUNTER_REPAIR_PROMPT = """\
Previous counter advice failed validation.

Validation feedback:
{feedback}

Original advice:
{advice}

Matchup data:
{matchup_data}

High-elo reference context:
{rag_context}

Rule-based baseline:
{baseline_plan}

Rewrite using exactly these sections:
MATCHUP READ
LANE PLAN
MID GAME
LATE GAME
ITEM PLAN

Keep it concise, specific, and grounded in the matchup data.
"""


AI_COACH_PROMPT = """\
You are the user's personalized League of Legends AI coach.
Use the deterministic coach engine as source of truth, then speak like a real esports coach: direct, specific, and evidence-bound.

COACH ENGINE FACTS
{coach_context}

MATCH DATA
{match_data}

TIMELINE DATA
{timeline_data}

RETRIEVED HIGH-ELO CONTEXT
{rag_context}

Internal orchestration:
1. Read the evidence packet.
2. Use retrieved high-elo context only when it supports the match facts.
3. Write a customized coach report.
4. Check your own answer for unsupported claims before final output.

Output exactly these sections:

COACH READ
[One short paragraph: state the PRIMARY FAILURE directly, using the exact metric from coach facts when available. Do not say "several areas" unless you name the one review anchor first.]

WHAT YOU DID RIGHT
[Name one positive signal from the match facts. Explain why it matters without distracting from the primary failure.]

ROLE EXECUTION
[Explain whether {champion} {position} fulfilled the comp job. Mention the player's job and one thing they should not confuse with another teammate's job.]

TURNING POINTS
- [Timestamp/evidence] What happened: ... Why it mattered: ... Replay checklist: wave/vision/cooldown/position.
- [Timestamp/evidence] What happened: ... Why it mattered: ... Replay checklist: wave/vision/cooldown/position.

PRACTICE ASSIGNMENT
[One measurable drill or trigger rule for the next similar game. Include a target number or a clear pass/fail checklist.]

Rules:
- The coach engine facts are authoritative; do not contradict them.
- If coach facts include "Primary Failure", use it as the center of the report.
- If coach facts include "Positive Signal", use it in WHAT YOU DID RIGHT.
- If data quality is low, say what cannot be proven.
- Do not diagnose lane from unreliable CS@10.
- In a loss, high KP with low damage/high deaths is possible low-quality participation, not automatic praise.
- In a win, say exactly what to keep repeating; do not write "keep the winning pattern" without naming the pattern.
- Do not assign another champion's split-push job to this player.
- Do not recommend offensive damage items as anti-burst tools.
- Never invent exact death causes, wave state, voice comms, or objective control if the data does not show them; ask the player to verify that point in replay.
- For early deaths, give a hypothesis to verify, such as solo-kill trade, jungle/support gank, collapse, or objective setup mistake, based only on timeline evidence.
- Avoid vague words like "try", "consider", "usually", and "play safe".
- Use at least one real number from the match.
- Keep the full report under 310 words.
"""


AI_COACH_REPAIR_PROMPT = """\
Previous AI coach report failed reflection.

Feedback:
{feedback}

Original report:
{text}

Coach engine facts:
{coach_context}

Rewrite using exactly these sections:
COACH READ
WHAT YOU DID RIGHT
ROLE EXECUTION
TURNING POINTS
PRACTICE ASSIGNMENT

Rules:
- Keep the deterministic coach facts as source of truth.
- Include at least one real number.
- Respect data confidence.
- Include one positive signal if coach facts provide it.
- Do not fabricate exact death cause, wave state, voice comms, or objective control.
- TURNING POINTS must include what happened, why it mattered, and a replay checklist.
- PRACTICE ASSIGNMENT must be measurable or pass/fail.
- Avoid vague words like "try", "consider", "usually", and "play safe".
- Keep under 310 words.
"""


def _llm(prompt: str) -> str:
    try:
        import ollama

        response = ollama.generate(
            model=OLLAMA_MODEL,
            prompt=prompt,
            options={"temperature": 0.2, "top_p": 0.9},
        )
        return response.get("response", "").strip()
    except Exception as exc:
        return f"LLM unavailable: {exc}"


def _clean_output(text: str) -> str:
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text or "").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _strategic_fallback(win: bool, champion: str, above_avg: str, below_avg: str) -> str:
    result_note = "win" if win else "loss"
    return (
        f"Main Diagnosis: Evidence: {above_avg or below_avg or 'available metrics'} in a {result_note}. Meaning: {champion or 'This champion'} should repeat the strongest signal while fixing the clearest gap. Action: review the top gap before queueing next game.\n"
        f"Lane Phase: Evidence: {below_avg or 'lane-specific data unclear from available data'}. Meaning: lane diagnosis needs CS@10, gold@10, and death timing. Action: use replay to decide pressure, stabilize, or move with jungle.\n"
        "Threat Handling: Evidence: enemy threat cause is unclear from available data. Meaning: do not assign blame without replay confirmation. Action: review deaths around fog, spell hold, and defensive item timing."
    )


def _counter_fallback(your_champ: str, your_pos: str, enemy_champ: str, matchup_data: str) -> str:
    return build_counter_plan(your_champ, your_pos, enemy_champ, matchup_data)


def _log(state: CounterState, message: str) -> None:
    writer = state.get("status_writer")
    if writer is not None:
        writer(message)


def _search_counter_context(your_champ: str, your_pos: str, enemy_champ: str) -> tuple[str, list[str]]:
    queries = [
        (f"{your_champ} vs {enemy_champ} {your_pos} matchup trading levels abilities", YOUTUBE_COLLECTION, 2),
        (f"Challenger {your_champ} {your_pos} versus {enemy_champ} items lane", CHALLENGER_COLLECTION, 3),
    ]

    docs: list[dict] = []
    for query, collection, k in queries:
        docs.extend(search_rag(query, collection=collection, k=k))

    if not docs:
        return "No specific RAG context found. Use matchup data and champion knowledge.", ["Master+ NA match dataset"]

    seen_content = set()
    unique_docs = []
    for doc in docs:
        content = doc.get("content", "").strip()
        if content and content not in seen_content:
            unique_docs.append(doc)
            seen_content.add(content)

    context = "\n".join(doc.get("content", "") for doc in unique_docs)[:MAX_CONTEXT_CHARS]
    sources = sorted({doc.get("source", "RAG knowledge base") for doc in docs})
    return context, sources


def _search_review_context(champion: str, position: str, coach_context: str, match_data: str) -> tuple[str, list[str]]:
    queries = [
        (f"Challenger {champion} {position} post game review deaths damage vision objective setup", CHALLENGER_COLLECTION, 3),
        (f"{champion} {position} guide teamfight lane objective coaching", YOUTUBE_COLLECTION, 2),
    ]
    docs: list[dict] = []
    for query, collection, k in queries:
        docs.extend(search_rag(query, collection=collection, k=k))

    if not docs:
        return "No specific RAG context found. Use coach engine facts and champion knowledge.", ["Coach engine facts"]

    seen_content = set()
    unique_docs = []
    for doc in docs:
        content = doc.get("content", "").strip()
        if content and content not in seen_content:
            unique_docs.append(doc)
            seen_content.add(content)
    context = "\n".join(doc.get("content", "") for doc in unique_docs)[:MAX_CONTEXT_CHARS]
    sources = sorted({doc.get("source", "RAG knowledge base") for doc in unique_docs})
    return context, sources


def _build_coaching_context(state: CoachingState) -> CoachingState:
    labels = COACHING_LABELS
    match_data = state.get("match_data", "")[:MAX_CONTEXT_CHARS]
    return {
        "labels": labels,
        "match_data": match_data,
        "timeline_data": state.get("timeline_data", "")[:MAX_CONTEXT_CHARS],
        "knowledge_context": build_knowledge_context(
            state.get("champion", ""),
            state.get("position", ""),
            match_data,
        ),
        "repair_count": state.get("repair_count", 0),
    }


def _draft_coaching_report(state: CoachingState) -> CoachingState:
    prompt = STRATEGIC_PROMPT.format(
        result="WIN" if state.get("win") else "LOSS",
        match_data=state.get("match_data", "")[:MAX_CONTEXT_CHARS],
        timeline_data=state.get("timeline_data", "")[:MAX_CONTEXT_CHARS],
        champion=state.get("champion", ""),
        position=state.get("position", ""),
        above_avg=state.get("above_avg", "none listed"),
        below_avg=state.get("below_avg", "none listed"),
        knowledge_context=state.get("knowledge_context", "No extra knowledge."),
    )
    return {"draft": _clean_output(_llm(prompt))}


def _reflect_coaching_report(state: CoachingState) -> CoachingState:
    passed, feedback = _judge_coaching_output(state)
    return {"passed_reflection": passed, "reflection_feedback": feedback}


def _repair_coaching_report(state: CoachingState) -> CoachingState:
    repaired = _clean_output(_llm(STRATEGIC_REPAIR_PROMPT.format(
        feedback=state.get("reflection_feedback", "failed validation"),
        labels="\n".join(f"{label}:" for label in state.get("labels", COACHING_LABELS)),
        text=state.get("draft", ""),
        match_data=state.get("match_data", "")[:MAX_CONTEXT_CHARS],
        above_avg=state.get("above_avg", "none listed"),
        below_avg=state.get("below_avg", "none listed"),
    )))
    if repaired.startswith("LLM unavailable"):
        repaired = state.get("draft", "")
    return {"draft": repaired, "repair_count": state.get("repair_count", 0) + 1}


def _finalize_coaching_report(state: CoachingState) -> CoachingState:
    draft = state.get("draft", "")
    labels = state.get("labels", COACHING_LABELS)
    if draft.startswith("LLM unavailable") or not _has_colon_labels(draft, labels):
        draft = _strategic_fallback(
            bool(state.get("win")),
            state.get("champion", ""),
            state.get("above_avg", "none listed"),
            state.get("below_avg", "none listed"),
        )
    return {"final": draft}


def _coaching_next_step(state: CoachingState) -> Literal["repair", "final"]:
    if state.get("passed_reflection") or state.get("repair_count", 0) >= MAX_REPAIRS:
        return "final"
    return "repair"


def _build_matchup_summary(state: CounterState) -> CounterState:
    baseline = build_counter_plan(
        state.get("your_champ", ""),
        state.get("your_pos", ""),
        state.get("enemy_champ", ""),
        state.get("matchup_data", ""),
    )
    return {
        "matchup_summary": state.get("matchup_data", "")[:MAX_CONTEXT_CHARS],
        "baseline_plan": baseline[:MAX_CONTEXT_CHARS],
        "repair_count": state.get("repair_count", 0),
    }


def _retrieve_counter_context(state: CounterState) -> CounterState:
    _log(state, "Checking matchup references...")
    rag_context, sources = _search_counter_context(
        state.get("your_champ", ""),
        state.get("your_pos", ""),
        state.get("enemy_champ", ""),
    )
    return {"rag_context": rag_context, "sources": sources}


def _draft_counter_plan(state: CounterState) -> CounterState:
    _log(state, "Drafting game plan...")
    advice = _clean_output(_llm(COUNTER_DRAFT_PROMPT.format(
        matchup_data=state.get("matchup_summary", state.get("matchup_data", ""))[:MAX_CONTEXT_CHARS],
        baseline_plan=state.get("baseline_plan", "")[:MAX_CONTEXT_CHARS],
        rag_context=state.get("rag_context", "")[:MAX_CONTEXT_CHARS],
        your_champ=state.get("your_champ", ""),
        enemy_champ=state.get("enemy_champ", ""),
    )))
    return {"draft": advice}


def _reflect_counter_plan(state: CounterState) -> CounterState:
    _log(state, "Reviewing specificity and data grounding...")
    passed, feedback = _judge_counter_output(state)
    return {"passed_reflection": passed, "reflection_feedback": feedback}


def _repair_counter_plan(state: CounterState) -> CounterState:
    _log(state, "Tightening the guide...")
    repaired = _clean_output(_llm(COUNTER_REPAIR_PROMPT.format(
        feedback=state.get("reflection_feedback", "failed validation"),
        advice=state.get("draft", ""),
        matchup_data=state.get("matchup_summary", state.get("matchup_data", ""))[:MAX_CONTEXT_CHARS],
        rag_context=state.get("rag_context", "")[:MAX_CONTEXT_CHARS],
        baseline_plan=state.get("baseline_plan", "")[:MAX_CONTEXT_CHARS],
    )))
    if repaired.startswith("LLM unavailable"):
        repaired = state.get("draft", "")
    return {"draft": repaired, "repair_count": state.get("repair_count", 0) + 1}


def _finalize_counter_plan(state: CounterState) -> CounterState:
    draft = state.get("draft", "")
    if (
        draft.startswith("LLM unavailable")
        or not _has_section_headers(draft, COUNTER_LABELS)
        or not state.get("passed_reflection", False)
    ):
        draft = _counter_fallback(
            state.get("your_champ", ""),
            state.get("your_pos", ""),
            state.get("enemy_champ", ""),
            state.get("matchup_data", ""),
        )
    return {"final": draft}


def _counter_next_step(state: CounterState) -> Literal["repair", "final"]:
    if state.get("passed_reflection") or state.get("repair_count", 0) >= MAX_REPAIRS:
        return "final"
    return "repair"


def _retrieve_ai_coach_context(state: AICoachState) -> AICoachState:
    rag_context, sources = _search_review_context(
        state.get("champion", ""),
        state.get("position", ""),
        state.get("coach_context", ""),
        state.get("match_data", ""),
    )
    return {"rag_context": rag_context, "sources": sources, "repair_count": state.get("repair_count", 0)}


def _draft_ai_coach_report(state: AICoachState) -> AICoachState:
    knowledge_context = build_knowledge_context(
        state.get("champion", ""),
        state.get("position", ""),
        state.get("match_data", ""),
    )
    rag_context = (
        f"{state.get('rag_context', '')[:MAX_CONTEXT_CHARS]}\n\n"
        f"Injected champion/role rules:\n{knowledge_context}"
    )
    draft = _clean_output(_llm(AI_COACH_PROMPT.format(
        coach_context=state.get("coach_context", "")[:MAX_CONTEXT_CHARS],
        match_data=state.get("match_data", "")[:MAX_CONTEXT_CHARS],
        timeline_data=state.get("timeline_data", "")[:MAX_CONTEXT_CHARS],
        rag_context=rag_context[:MAX_CONTEXT_CHARS],
        champion=state.get("champion", ""),
        position=state.get("position", ""),
    )))
    return {"draft": draft}


def _reflect_ai_coach_report(state: AICoachState) -> AICoachState:
    passed, feedback = _judge_ai_coach_output(state)
    return {"passed_reflection": passed, "reflection_feedback": feedback}


def _repair_ai_coach_report(state: AICoachState) -> AICoachState:
    repaired = _clean_output(_llm(AI_COACH_REPAIR_PROMPT.format(
        feedback=state.get("reflection_feedback", "failed validation"),
        text=state.get("draft", ""),
        coach_context=state.get("coach_context", "")[:MAX_CONTEXT_CHARS],
    )))
    if repaired.startswith("LLM unavailable"):
        repaired = state.get("draft", "")
    return {"draft": repaired, "repair_count": state.get("repair_count", 0) + 1}


def _finalize_ai_coach_report(state: AICoachState) -> AICoachState:
    draft = state.get("draft", "")
    if (
        draft.startswith("LLM unavailable")
        or not _has_section_headers(draft, AI_COACH_LABELS)
        or not state.get("passed_reflection", False)
    ):
        context = state.get("coach_context", "")
        diagnosis = _extract_context_value(context, "Coach Diagnosis")
        role = _extract_context_value(context, "Role Responsibility")
        turns = _extract_context_value(context, "Turning Points")
        priority = _extract_context_value(context, "One Priority Fix")
        primary_failure = _extract_context_value(context, "Primary Failure")
        positive_signal = _extract_context_value(context, "Positive Signal")
        metrics = _extract_context_value(context, "Match Metrics")
        replay = _extract_context_value(context, "Replay Checkpoints")
        data_health = _extract_context_value(context, "Data Health")
        coach_read = diagnosis or "Start from the deterministic coach diagnosis and verify it in replay."
        if primary_failure and primary_failure.lower() not in coach_read.lower():
            coach_read = f"Primary failure: {primary_failure}. {coach_read}"
        assignment = priority or "Review the primary coach-engine gap before changing broader strategy."
        assignment = (
            f"{assignment} Pass/fail rule: before crossing river or joining an objective, name enemy threat location, "
            "your defensive cooldown, and nearest safe teammate; if one answer is unknown, reset vision first."
        )
        draft = (
            "COACH READ\n"
            f"{coach_read} "
            f"{metrics or data_health}\n\n"
            "WHAT YOU DID RIGHT\n"
            f"{positive_signal or 'No clear above-benchmark positive stood out; keep the review focused on the primary failure.'}\n\n"
            "ROLE EXECUTION\n"
            f"{role or 'Judge the player by the role responsibility defined by the comp, not by generic stats alone.'}\n\n"
            "TURNING POINTS\n"
            f"- {turns or replay or 'First death / first objective setup'} What happened: verify the exact setup in replay. "
            "Why it mattered: this is where the game state changed or your role execution was tested. "
            "Replay checklist: wave state, vision entry, key cooldowns, and position relative to frontline.\n"
            "- Later death chain What happened: classify deaths 3+ as tactical sacrifice, greedy overstep, or poor fight positioning. "
            "Why it mattered: not every death is equal, but repeated preventable deaths create the snowball. "
            "Replay checklist: what you gained, what team would lose if you backed off, and whether 300g plus tempo was worth it.\n\n"
            "PRACTICE ASSIGNMENT\n"
            f"{assignment}"
        )
    return {"final": draft}


def _extract_context_value(context: str, label: str) -> str:
    pattern = rf"(^|\n){re.escape(label)}:\s*(.+?)(?=\n[A-Z][A-Za-z ]+?:|\Z)"
    match = re.search(pattern, context or "", flags=re.S)
    if not match:
        return ""
    return " ".join(match.group(2).split())


def _ai_coach_next_step(state: AICoachState) -> Literal["repair", "final"]:
    if state.get("passed_reflection") or state.get("repair_count", 0) >= MAX_REPAIRS:
        return "final"
    return "repair"


@lru_cache(maxsize=1)
def _coaching_graph():
    from langgraph.graph import END, StateGraph

    graph = StateGraph(CoachingState)
    graph.add_node("build_match_context", _build_coaching_context)
    graph.add_node("draft_coaching_report", _draft_coaching_report)
    graph.add_node("reflect_coaching_report", _reflect_coaching_report)
    graph.add_node("repair_coaching_report", _repair_coaching_report)
    graph.add_node("finalize_coaching_report", _finalize_coaching_report)

    graph.set_entry_point("build_match_context")
    graph.add_edge("build_match_context", "draft_coaching_report")
    graph.add_edge("draft_coaching_report", "reflect_coaching_report")
    graph.add_conditional_edges(
        "reflect_coaching_report",
        _coaching_next_step,
        {"repair": "repair_coaching_report", "final": "finalize_coaching_report"},
    )
    graph.add_edge("repair_coaching_report", "reflect_coaching_report")
    graph.add_edge("finalize_coaching_report", END)
    return graph.compile()


@lru_cache(maxsize=1)
def _counter_graph():
    from langgraph.graph import END, StateGraph

    graph = StateGraph(CounterState)
    graph.add_node("build_matchup_summary", _build_matchup_summary)
    graph.add_node("retrieve_rag_context", _retrieve_counter_context)
    graph.add_node("draft_counter_plan", _draft_counter_plan)
    graph.add_node("reflect_counter_plan", _reflect_counter_plan)
    graph.add_node("repair_counter_plan", _repair_counter_plan)
    graph.add_node("finalize_counter_plan", _finalize_counter_plan)

    graph.set_entry_point("build_matchup_summary")
    graph.add_edge("build_matchup_summary", "retrieve_rag_context")
    graph.add_edge("retrieve_rag_context", "draft_counter_plan")
    graph.add_edge("draft_counter_plan", "reflect_counter_plan")
    graph.add_conditional_edges(
        "reflect_counter_plan",
        _counter_next_step,
        {"repair": "repair_counter_plan", "final": "finalize_counter_plan"},
    )
    graph.add_edge("repair_counter_plan", "reflect_counter_plan")
    graph.add_edge("finalize_counter_plan", END)
    return graph.compile()


@lru_cache(maxsize=1)
def _ai_coach_graph():
    from langgraph.graph import END, StateGraph

    graph = StateGraph(AICoachState)
    graph.add_node("retrieve_rag_context", _retrieve_ai_coach_context)
    graph.add_node("draft_ai_coach_report", _draft_ai_coach_report)
    graph.add_node("reflect_ai_coach_report", _reflect_ai_coach_report)
    graph.add_node("repair_ai_coach_report", _repair_ai_coach_report)
    graph.add_node("finalize_ai_coach_report", _finalize_ai_coach_report)

    graph.set_entry_point("retrieve_rag_context")
    graph.add_edge("retrieve_rag_context", "draft_ai_coach_report")
    graph.add_edge("draft_ai_coach_report", "reflect_ai_coach_report")
    graph.add_conditional_edges(
        "reflect_ai_coach_report",
        _ai_coach_next_step,
        {"repair": "repair_ai_coach_report", "final": "finalize_ai_coach_report"},
    )
    graph.add_edge("repair_ai_coach_report", "reflect_ai_coach_report")
    graph.add_edge("finalize_ai_coach_report", END)
    return graph.compile()


def _run_coaching_sequential(state: CoachingState) -> CoachingState:
    state.update(_build_coaching_context(state))
    state.update(_draft_coaching_report(state))
    state.update(_reflect_coaching_report(state))
    if _coaching_next_step(state) == "repair":
        state.update(_repair_coaching_report(state))
        state.update(_reflect_coaching_report(state))
    state.update(_finalize_coaching_report(state))
    return state


def _run_counter_sequential(state: CounterState) -> CounterState:
    state.update(_build_matchup_summary(state))
    state.update(_retrieve_counter_context(state))
    state.update(_draft_counter_plan(state))
    state.update(_reflect_counter_plan(state))
    if _counter_next_step(state) == "repair":
        state.update(_repair_counter_plan(state))
        state.update(_reflect_counter_plan(state))
    state.update(_finalize_counter_plan(state))
    return state


def _run_ai_coach_sequential(state: AICoachState) -> AICoachState:
    state.update(_retrieve_ai_coach_context(state))
    state.update(_draft_ai_coach_report(state))
    state.update(_reflect_ai_coach_report(state))
    if _ai_coach_next_step(state) == "repair":
        state.update(_repair_ai_coach_report(state))
        state.update(_reflect_ai_coach_report(state))
    state.update(_finalize_ai_coach_report(state))
    return state


def run_strategic_agent(
    match_data: str,
    timeline_data: str,
    champion: str = "",
    position: str = "",
    outcome: str = "UNKNOWN",
    above_avg: str = "none listed",
    below_avg: str = "none listed",
    win: bool = False,
) -> str:
    """Return a reflected 3-card coaching report for Player Review."""
    del outcome
    state: CoachingState = {
        "match_data": match_data,
        "timeline_data": timeline_data,
        "champion": champion,
        "position": position,
        "win": win,
        "above_avg": above_avg,
        "below_avg": below_avg,
        "repair_count": 0,
    }
    try:
        result = _coaching_graph().invoke(state)
    except Exception:
        result = _run_coaching_sequential(state)
    return result.get("final", "")


def run_counter_agents(
    your_champ: str,
    your_pos: str,
    enemy_champ: str,
    matchup_data: str,
    status_writer: Callable[[str], None] | None = None,
) -> tuple[str, list[str]]:
    """Run the Counter Guide graph and return advice plus source labels."""
    state: CounterState = {
        "your_champ": your_champ,
        "your_pos": your_pos,
        "enemy_champ": enemy_champ,
        "matchup_data": matchup_data,
        "status_writer": status_writer,
        "repair_count": 0,
    }
    try:
        result = _counter_graph().invoke(state)
    except Exception:
        result = _run_counter_sequential(state)
    return result.get("final", ""), result.get("sources", [])


def run_ai_coach_report_agent(
    coach_context: str,
    match_data: str,
    timeline_data: str,
    champion: str = "",
    position: str = "",
) -> tuple[str, list[str]]:
    """Generate a personalized AI coach report with RAG and reflection guards."""
    state: AICoachState = {
        "coach_context": coach_context,
        "match_data": match_data,
        "timeline_data": timeline_data,
        "champion": champion,
        "position": position,
        "repair_count": 0,
    }
    try:
        result = _ai_coach_graph().invoke(state)
    except Exception:
        result = _run_ai_coach_sequential(state)
    return result.get("final", ""), result.get("sources", [])
