"""Match-grounded chat helper for Player Review follow-up questions."""
from __future__ import annotations

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from core.config import OLLAMA_MODEL

CHAT_MODEL = OLLAMA_MODEL
MAX_CONTEXT_CHARS = 4_500
MAX_HISTORY_TURNS = 4


class _UnavailableChat:
    def __init__(self, reason: str):
        self.reason = reason

    def predict(self, input: str) -> str:
        del input
        return f"AI coach not available: {self.reason}"


class _MatchCoachChat:
    """Small stateful chat wrapper that grounds every answer in match context."""

    def __init__(self, initial_context: str):
        self.context = initial_context[:MAX_CONTEXT_CHARS]
        self.history: list[tuple[str, str]] = []

    def predict(self, input: str) -> str:
        history_text = "\n".join(
            f"Player: {question}\nCoach: {answer}"
            for question, answer in self.history[-MAX_HISTORY_TURNS:]
        )
        prompt = f"""\
You are a match-specific League of Legends coach.
Use only the match context below. Do not give generic advice.

MATCH CONTEXT
{self.context}

RECENT CHAT
{history_text or "None"}

PLAYER QUESTION
{input}

Answer with exactly these labels:

COACH READ: [direct review judgment in one sentence]
MATCH EVIDENCE: [evidence from this match, with numbers/champions/items if available]
TACTICAL ADJUSTMENT: [how this exact game phase or fight should have been handled]

Rules:
- If the context does not contain enough evidence, say what is unknown.
- For item questions, judge build intent against enemy win condition, not just overlap with reference builds.
- Credit Locket or other defensive support items when they answer burst, engage, or first-combo damage.
- Never describe offensive damage items as anti-burst or survivability tools.
- For burst/CC survival, recommend real defensive answers when role-appropriate: Locket, Celestial Opposition, Zhonya, Banshee, Mikael, Exhaust, spacing, or cooldown tracking.
- If the player is support, do not suggest mage damage items as the main answer to burst/CC.
- For lane vs roam questions, review whether this match's lane phase served the draft and objective plan.
- If the question is about lane or objective fights, do not answer with itemization unless the item timing directly affected that fight.
- Do not turn post-game review into a generic next-game training plan.
- Do not say "based on the information provided".
- Keep the full answer under 120 words.
"""
        try:
            import ollama

            response = ollama.generate(
                model=CHAT_MODEL,
                prompt=prompt,
                options={"temperature": 0.2, "top_p": 0.9},
            )
            answer = response.get("response", "").strip()
        except Exception as exc:
            answer = f"AI coach not available: {exc}"
        self.history.append((input, answer))
        return answer


def create_chat_chain(initial_context: str):
    return _MatchCoachChat(initial_context)
