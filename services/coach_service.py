"""
Rule-based coaching logic — deterministic, no LLM.

Rule:
  If a piece of information can be calculated with rules → use rules.
  Only use LLM for natural language explanation and synthesis.
"""
from __future__ import annotations
import re
from core.config import CHALL_AVG_ITEM_MIN
from models.schemas import MatchVerdict


# ─── Match Verdict (rule-based, instant) ─────────────────────────────────────

def generate_match_verdict(
    player_data: dict,
    chall_avg: dict,
    timeline_data: dict | None,
) -> MatchVerdict:
    """
    Deterministic 4-signal verdict — no LLM involved.
    Signals are ranked by severity; top mistake and top strength are picked.
    """
    mistakes: list[dict] = []
    strengths: list[dict] = []
    tl = timeline_data or {}

    # ── Death timing ──────────────────────────────────────────────────────────
    first_death = tl.get("first_death_minute")
    if first_death is not None:
        if first_death < 5:
            mistakes.append({
                "text": f"First death at minute {int(first_death)} — likely unwarded jungle path",
                "severity": 3, "cost_key": "death_timing",
                "first_death": first_death,
            })
        elif first_death < 8:
            mistakes.append({
                "text": f"First death at minute {int(first_death)} — early laning phase",
                "severity": 2, "cost_key": "death_timing",
                "first_death": first_death,
            })

    # ── Total deaths (normalized to per-30-min so long games aren't penalised) ──
    deaths     = player_data.get("deaths", 0)
    duration   = max(player_data.get("duration", 30), 1)   # game length in minutes
    chall_d    = chall_avg.get("deaths", 0)
    # Challenger avg is per-game; normalise both to per-30-min for fair comparison
    death_rate   = deaths   / (duration / 30)
    chall_rate   = chall_d  / (28       / 30)   # Challenger games average ~28 min
    death_gap    = death_rate - chall_rate
    if death_gap > 2.5:
        mistakes.append({
            "text": f"{int(deaths)} deaths in {duration}min ({death_rate:.1f}/30min vs Challenger {chall_rate:.1f}/30min)",
            "severity": 2, "cost_key": "deaths",
        })
    elif death_gap < -2:
        strengths.append({
            "text": f"Only {int(deaths)} deaths in {duration}min ({death_rate:.1f}/30min vs Challenger {chall_rate:.1f}/30min)"
        })

    # ── CS per minute ─────────────────────────────────────────────────────────
    cs_pm      = player_data.get("cs_per_min", 0)
    chall_cs   = chall_avg.get("cs_per_min", 0)
    cs_gap     = cs_pm - chall_cs
    if cs_gap < -1.5:
        mistakes.append({
            "text": f"CS/min {cs_pm:.1f} vs Challenger avg {chall_cs:.1f} ({cs_gap:+.1f})",
            "severity": 2, "cost_key": "cs_gap", "cs_gap": cs_gap,
        })
    elif cs_gap > 1.5:
        strengths.append({
            "text": f"CS/min {cs_pm:.1f} vs Challenger avg {chall_cs:.1f} ({cs_gap:+.1f})"
        })

    # ── Vision ────────────────────────────────────────────────────────────────
    vision      = player_data.get("vision", 0)
    chall_vis   = chall_avg.get("vision", 0)
    vision_gap  = vision - chall_vis
    if vision_gap > 15:
        strengths.append({
            "text": f"Vision score {vision} vs Challenger avg {chall_vis:.0f} ({vision_gap:+.0f})"
        })
    elif vision_gap < -15:
        mistakes.append({
            "text": f"Vision score {vision} vs Challenger avg {chall_vis:.0f} ({vision_gap:+.0f})",
            "severity": 1, "cost_key": "vision",
        })

    # ── KDA ───────────────────────────────────────────────────────────────────
    kda       = player_data.get("kda", 0)
    chall_kda = chall_avg.get("kda", 0)
    kda_gap   = kda - chall_kda
    if kda_gap > 1:
        strengths.append({
            "text": f"KDA {kda:.2f} vs Challenger avg {chall_kda:.2f} ({kda_gap:+.2f})"
        })

    # ── Item timing ───────────────────────────────────────────────────────────
    item_min = tl.get("first_item_minute")
    if item_min is not None:
        item_delay = round(item_min - CHALL_AVG_ITEM_MIN, 0)
        if item_delay > 3:
            mistakes.append({
                "text": f"Core item at minute {int(item_min)} (Challenger avg: {CHALL_AVG_ITEM_MIN} min)",
                "severity": 2, "cost_key": "item_delay", "item_delay": item_delay,
            })
        elif item_delay < 0:
            strengths.append({
                "text": f"Core item at minute {int(item_min)} — {abs(item_delay):.0f} min ahead of Challenger avg"
            })

    # ── Damage ────────────────────────────────────────────────────────────────
    dmg       = player_data.get("damage", 0)
    chall_dmg = chall_avg.get("damage", 0)
    dmg_gap   = dmg - chall_dmg
    if dmg_gap > 5000:
        strengths.append({
            "text": f"Damage {dmg:,} vs Challenger avg {chall_dmg:,} (+{dmg_gap:,})"
        })
    elif dmg_gap < -5000:
        mistakes.append({
            "text": f"Damage {dmg:,} vs Challenger avg {chall_dmg:,} ({dmg_gap:,})",
            "severity": 1, "cost_key": "damage",
        })

    # ── Pick best mistake / strength ──────────────────────────────────────────
    mistakes.sort(key=lambda x: x["severity"], reverse=True)
    top_mistake  = mistakes[0]  if mistakes  else None
    top_strength = strengths[0] if strengths else None
    second_strength = strengths[1] if len(strengths) > 1 else None

    win = player_data.get("win", False)

    # ── what_it_cost / even_better_if ─────────────────────────────────────────
    if top_mistake:
        ck = top_mistake.get("cost_key", "")
        if ck == "death_timing":
            fd = top_mistake.get("first_death", 0)
            what_it_cost = f"Death before minute {int(fd)} disrupted laning phase and delayed item timing"
        elif ck == "item_delay":
            delay = top_mistake.get("item_delay", 0)
            what_it_cost = f"Core item {int(delay)} min late → entered teamfights at reduced power"
        elif ck == "cs_gap":
            g = abs(top_mistake.get("cs_gap", 1.5))
            gold_lost = int(g * 14 * 20)   # ~14g/cs × ~20min
            what_it_cost = f"~{gold_lost:,}g of CS income lost — delayed item spike"
        elif ck == "deaths":
            what_it_cost = (
                "Respawn timers cost map control — fixing this converts close wins into dominant ones"
                if win else
                "Repeated respawn timers ceded map control and objective windows"
            )
        elif ck == "vision":
            what_it_cost = (
                "Low vision left objectives to chance — you won despite it, not because of it"
                if win else
                "Low vision directly cost objective control (dragon / baron)"
            )
        elif ck == "damage":
            what_it_cost = (
                "Below-average damage means teammates carried the DPS load this game"
                if win else
                "Below-average damage reduced teamfight impact"
            )
        else:
            what_it_cost = (
                "Small execution gap — eliminating it makes close wins more consistent"
                if win else
                "Reduced impact in mid-to-late teamfights"
            )
    else:
        what_it_cost = (
            "Clean execution — this is why the win felt controlled, not lucky"
            if win else
            "No major mistake identified — consistent performance"
        )

    # ── next_game_focus ───────────────────────────────────────────────────────
    if top_mistake:
        ck = top_mistake.get("cost_key", "")
        fd = top_mistake.get("first_death")
        if ck == "death_timing" and fd and fd < 5:
            next_game_focus = f"Ward river before minute {max(2, int(fd) - 1)} to spot jungle pressure"
        elif ck == "death_timing":
            next_game_focus = "Delay first death past minute 10 — recall at 60% HP in lane"
        elif ck == "cs_gap":
            next_game_focus = "Target 7.5+ CS/min — practice last-hitting between ability casts"
        elif ck == "item_delay":
            next_game_focus = f"Target first core item by minute {CHALL_AVG_ITEM_MIN} — recall immediately when gold allows"
        elif ck == "deaths":
            next_game_focus = "Track death timing in replay — identify which positions cost lives"
        elif ck == "vision":
            next_game_focus = "Place one control ward every back — minimum 3 per game"
        elif ck == "damage":
            next_game_focus = "Prioritize grouping for teamfights — DPS requires being in fights"
        else:
            next_game_focus = "Review replay for positioning in teamfights"
    else:
        next_game_focus = "Maintain current performance — work on consistency across games"

    training_goals = _generate_training_goals(top_mistake, chall_avg)

    # For wins: card 2 ("WHAT YOU DID WELL") shows the second strength if available,
    # otherwise reframes the top mistake as something minor despite winning.
    if win:
        if second_strength:
            card2_text = second_strength["text"]
        elif top_mistake:
            card2_text = f"You overcame {top_mistake['text'].split(' vs')[0].lower()} to secure the win"
        else:
            card2_text = "Consistent execution across all major metrics"
    else:
        card2_text = top_mistake["text"] if top_mistake else "No major mistake identified"

    return MatchVerdict(
        biggest_mistake=card2_text,
        strongest_point=top_strength["text"] if top_strength else "Consistent overall performance",
        what_it_cost=what_it_cost,
        next_game_focus=next_game_focus,
        training_goals=training_goals,
    )


def _generate_training_goals(top_mistake: dict | None, chall_avg: dict) -> list[str]:
    """Rule-based 3-game training goals — checkbox format, max 3."""
    if not top_mistake:
        return ["Maintain consistent performance across all 3 games"]

    ck  = top_mistake.get("cost_key", "")
    fd  = top_mistake.get("first_death")
    goals: list[str] = []

    if ck == "death_timing":
        fd_int = int(fd) if fd else 8
        goals.append(f"First death after {max(10, fd_int + 3)}:00")
        goals.append("Pre-10 min deaths ≤ 1")
        goals.append("Recall if HP < 60% before river contest")

    elif ck == "cs_gap":
        cs_gap = abs(top_mistake.get("cs_gap", 1.5))
        target = round(chall_avg.get("cs_per_min", 7.0) + 0.3, 1)
        goals.append(f"CS/min ≥ {target} (Challenger avg: {chall_avg.get('cs_per_min', 7.0):.1f})")
        goals.append("Last-hit under tower without missing a wave")
        goals.append("Recall only between waves, never mid-wave")

    elif ck == "item_delay":
        goals.append(f"First core item ≤ {CHALL_AVG_ITEM_MIN} min — recall the moment gold allows")
        goals.append("No unnecessary base trips before item completion")
        goals.append("Track item timing in post-game — note the exact minute")

    elif ck == "deaths":
        target_rate = chall_avg.get("deaths", 3.0) / (28 / 30)
        goals.append(f"Deaths/30min ≤ {target_rate:.1f} — track whether deaths cluster in laning or teamfights")
        goals.append("After each death: identify the exact decision that caused it")
        goals.append("No solo fights without vision on enemy jungler")

    elif ck == "vision":
        target_vis = int(chall_avg.get("vision", 40) * 0.85)
        goals.append(f"Vision score ≥ {target_vis} every game")
        goals.append("Buy 1 control ward on every recall")
        goals.append("Place ward at dragon/baron pit before every timer")

    elif ck == "damage":
        goals.append("Join every teamfight — no split-pushing in decisive fights")
        goals.append("Track personal damage in post-game — aim to top team output")
        goals.append("Position to hit 3+ enemies per spell rotation")

    return goals[:3]


# ─── Rule Validator (replaces Reflection Agent) ───────────────────────────────

_VAGUE_WORDS = [
    "generally", "usually", "try to", "consider",
    "might", "could potentially", "in most cases",
]
_ACTION_WORDS = [
    "ward", "delay", "prioritize", "avoid", "push",
    "track", "focus", "build", "rush", "target",
    "recall", "group", "rotate", "buy", "place",
]

def validate_coaching_output(text: str, match_data: dict) -> dict:
    """
    Deterministic output validator — no LLM.
    Returns {"passed": bool, "failed_checks": list[str]}.
    """
    lower = text.lower()
    checks = {
        "has_number":        bool(re.search(r'\d+\.?\d*', text)),
        "has_action":        any(w in lower for w in _ACTION_WORDS),
        "no_vague":          not any(w in lower for w in _VAGUE_WORDS),
        "mentions_champion": match_data.get("champion", "").lower() in lower,
        "no_wrong_items":    not ("rabadon" in lower and "surviv" in lower),
    }
    failed = [k for k, v in checks.items() if not v]
    return {"passed": not failed, "failed_checks": failed}


# ─── Gold diff chart auto-annotation text ────────────────────────────────────

def gold_diff_summary(gold_diff_by_minute: dict, first_death_min: float | None, win: bool = False) -> str:
    """One-sentence chart caption generated from rules, with win/loss context."""
    if not gold_diff_by_minute:
        return ""
    gold_at_10 = gold_diff_by_minute.get(10, gold_diff_by_minute.get(9, None))
    max_gold   = max(gold_diff_by_minute.values(), default=0)
    min_gold   = min(gold_diff_by_minute.values(), default=0)
    death_str  = f" after first death at minute {int(first_death_min)}" if first_death_min else ""

    if gold_at_10 is not None and gold_at_10 < -500:
        if win:
            return (
                f"You were behind in gold{death_str} (deficit peaked at {abs(min_gold):,}g) "
                f"but won — your teamfight value outweighed the gold deficit."
            )
        return (
            f"Gold went negative{death_str} and never fully recovered — "
            f"deficit peaked at {abs(min_gold):,}g."
        )
    if gold_at_10 is not None and gold_at_10 > 1_000:
        if win:
            return (
                f"Strong gold lead at 10 min (+{gold_at_10:,}g) — you converted the early advantage "
                f"into a controlled victory. Keep pressing early leads."
            )
        return (
            f"Strong gold lead at 10 min (+{gold_at_10:,}g), "
            f"but advantage narrowed in mid game — item timing was the key window."
        )
    if max_gold > 0 and min_gold < 0:
        if win:
            return (
                f"Gold swung from +{max_gold:,}g to {min_gold:,}g — volatile game, "
                f"but you closed it out. Steadier laning would make wins less coin-flip."
            )
        return f"Gold curve swung from +{max_gold:,}g to {min_gold:,}g — volatile laning phase."
    if min_gold < -500:
        if win:
            return (
                f"Consistent gold deficit throughout, yet you secured the win — "
                f"macro decisions and teamplay compensated for the laning disadvantage."
            )
        return f"Consistent gold deficit throughout — never gained lead over enemy laner."
    return (
        f"Gold parity through laning — {'win secured through mid/late-game execution.' if win else 'game decided in mid/late.'}"
    )


# ─── KPI explanation labels ───────────────────────────────────────────────────

_KPI_EXPLANATIONS = {
    "deaths": {
        "bad":  "Repeated deaths reduced tempo and delayed item timing.",
        "good": "Clean survival improved map presence and objective windows.",
    },
    "vision": {
        "bad":  "Low vision likely caused uncontested objectives.",
        "good": "Strong warding gave your team objective control windows.",
    },
    "cs_per_min": {
        "bad":  "CS gap = delayed item timing = weaker teamfights.",
        "good": "Efficient farming translated to earlier item spikes.",
    },
    "kda": {
        "bad":  "Low KDA reflects deaths outweighing kill contribution.",
        "good": "High KDA shows strong survival and fight contribution.",
    },
    "damage": {
        "bad":  "Below-average damage — check if deaths limited fight time.",
        "good": "High damage output — strong teamfight presence.",
    },
    "kp": {
        "bad":  "Low kill participation — possibly split or missing fights.",
        "good": "High kill participation — grouping with team effectively.",
    },
    "damage_share": {
        "bad":  "Low damage share — consider positioning in teamfights.",
        "good": "High damage share — carrying the team's DPS output.",
    },
}

def get_kpi_explanation(key: str, good: bool) -> str:
    entry = _KPI_EXPLANATIONS.get(key)
    if not entry:
        return ""
    return entry["good"] if good else entry["bad"]


# ─── Progress Tracker (last N games) ─────────────────────────────────────────

_ISSUE_LABELS = {
    "deaths":    "Early/excess deaths",
    "cs_per_min":"Low CS/min",
    "vision":    "Low vision score",
}

_ISSUE_FOCUS = {
    "deaths":     "Survive longer — track which game phase you die most in each game",
    "cs_per_min": "Farm consistency — hit 7+ CS/min by minute 10 before grouping",
    "vision":     "Control wards — buy one on every recall, place before objectives",
}


def get_recurring_issues(
    parsed_matches: list[dict],
    chall_avg: dict,
    n: int = 5,
) -> dict | None:
    """
    Scan the last `n` parsed matches for the most frequently failing signal.

    Each parsed match dict must contain: deaths, cs_per_min, vision.
    chall_avg must contain the same keys.

    Returns None if fewer than 3 matches are available.
    Returns a dict with:
        issue         — label of top recurring problem
        games_affected— count of games where issue appeared
        out_of        — games analysed (≤ n)
        improving     — bool (newer 2 games better than older 3?)
        trend_delta   — numeric change (negative = improving)
        all_issues    — {issue_key: count} for all signals
    """
    recent = parsed_matches[:n]
    if len(recent) < 3:
        return None

    chall_deaths = chall_avg.get("deaths", 3.5)
    chall_cs     = chall_avg.get("cs_per_min", 7.0)
    chall_vis    = chall_avg.get("vision", 40.0)

    _chall_rate = chall_deaths / (28 / 30)

    def _flags(m: dict) -> dict[str, bool]:
        _dur = max(m.get("duration", 30), 1)
        _death_rate = m.get("deaths", 0) / (_dur / 30)
        return {
            "deaths":     _death_rate > _chall_rate + 1.0,
            "cs_per_min": m.get("cs_per_min", 0) < chall_cs  - 1.5,
            "vision":     m.get("vision", 0)      < chall_vis * 0.70,
        }

    counts: dict[str, int] = {"deaths": 0, "cs_per_min": 0, "vision": 0}
    for m in recent:
        for key, bad in _flags(m).items():
            if bad:
                counts[key] += 1

    top_key   = max(counts, key=counts.get)
    top_count = counts[top_key]
    if top_count == 0:
        return None          # no recurring issues — all good

    # Trend: compare newest 2 vs oldest (up to 3)
    improving    = False
    trend_delta  = 0.0
    if len(recent) >= 5:
        older = recent[2:5]
        newer = recent[:2]

        def _score(m: dict) -> float:
            f = _flags(m)
            _dur = max(m.get("duration", 30), 1)
            _death_rate = m.get("deaths", 0) / (_dur / 30)
            return (
                (_death_rate - _chall_rate) / max(_chall_rate, 1) * f["deaths"]
                + (chall_cs - m.get("cs_per_min", 0)) / max(chall_cs, 1) * f["cs_per_min"]
                + (chall_vis - m.get("vision", 0)) / max(chall_vis, 1) * f["vision"]
            )

        older_avg = sum(_score(m) for m in older) / len(older)
        newer_avg = sum(_score(m) for m in newer) / len(newer)
        trend_delta  = round(newer_avg - older_avg, 2)
        improving    = trend_delta < -0.05   # meaningfully better

    return {
        "issue":          _ISSUE_LABELS.get(top_key, top_key),
        "issue_key":      top_key,
        "games_affected": top_count,
        "out_of":         len(recent),
        "improving":      improving,
        "trend_delta":    trend_delta,
        "focus":          _ISSUE_FOCUS.get(top_key, ""),
        "all_issues":     {_ISSUE_LABELS[k]: v for k, v in counts.items()},
    }
