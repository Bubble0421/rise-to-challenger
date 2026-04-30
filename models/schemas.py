"""Pydantic data models for structured coaching outputs."""
from pydantic import BaseModel


class MatchVerdict(BaseModel):
    biggest_mistake: str       # one sentence — the top negative signal
    strongest_point: str       # one sentence — the top positive signal
    what_it_cost: str          # one sentence — consequence of the mistake
    next_game_focus: str       # one sentence — kept for AI follow-up context
    training_goals: list[str]  # 2-3 checkbox-style goals for next 3 games


class CoachOutput(BaseModel):
    verdict: str            # one sentence — the main coaching finding
    why: list[str]          # 2-3 data-backed reasons (bullet points)
    do_next_game: list[str] # 1-3 specific actions with timing/metric targets
    confidence: str         # "High" / "Medium" / "Low"
    based_on: list[str]     # which metrics/data sources were used
