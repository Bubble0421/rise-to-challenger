"""Rule-based pre-game counter plans.

This is the product floor for Counter Guide: even if local AI is unavailable,
the guide should still produce matchup-specific lane, map, and item advice.
"""
from __future__ import annotations

import re


LOW_VALUE_ITEM_NAMES = {
    "Doran's Blade", "Doran's Ring", "Doran's Shield", "Cull",
    "Cloak of Agility", "Long Sword", "B. F. Sword", "Pickaxe",
    "Recurve Bow", "Amplifying Tome", "Needlessly Large Rod",
    "Ruby Crystal", "Sapphire Crystal", "Boots", "Berserker's Greaves",
}


PAIR_PLANS: dict[tuple[str, str, str], dict[str, object]] = {
    ("Jinx", "BOTTOM", "Caitlyn"): {
        "matchup": (
            "Lane is Caitlyn-favored even if the dataset is even: Caitlyn wins range, push, "
            "trap plates, and early HP pressure; Jinx wins by staying even into 2 items."
        ),
        "lane": [
            "Do not contest level 1 push unless support creates first CC.",
            "Trade after Caitlyn Q/net or headshot is down; preserve HP over chip damage.",
            "Hold Flame Chompers for trap follow-up, jungle gank, or Caitlyn E escape.",
        ],
        "mid": [
            "After bot tower falls, catch safe mid waves instead of matching Caitlyn alone.",
            "Fight dragons only after wave push; Jinx needs reset access, not blind river entry.",
        ],
        "late": (
            "Play front-to-back: rockets for safe DPS, chompers against dive, then step forward "
            "only after the first takedown activates the reset."
        ),
        "items": [
            ("Phantom Dancer / Infinity Edge", "2-item DPS spike; this is when the matchup flips."),
            ("Lord Dominik's Regards", "buy when armor or frontline blocks access to Caitlyn."),
        ],
    },
    ("Caitlyn", "BOTTOM", "Jinx"): {
        "matchup": (
            "Caitlyn should own the first three waves: range and traps must create plates before "
            "Jinx reaches stable two-item teamfights."
        ),
        "lane": [
            "Push first three waves, trap under tower, and punish Jinx last-hits.",
            "Do not waste net forward unless enemy support CC is already down.",
            "Crash wave before dragon setup so Jinx must choose CS or river.",
        ],
        "mid": [
            "Convert bot plates into first objective vision with support and jungle.",
            "Avoid equal front-to-back fights once Jinx has reset angles.",
        ],
        "late": "Siege with traps around objectives; never let Jinx enter fights with a free reset.",
        "items": [
            ("Infinity Edge / Rapid Firecannon", "extend poke and siege pressure."),
            ("Lord Dominik's Regards", "answer frontline before Jinx gets free DPS time."),
        ],
    },
    ("Lux", "UTILITY", "Nautilus"): {
        "matchup": "Lux has range advantage, but Nautilus wins if he reaches hook range before Q is available.",
        "lane": [
            "Stand outside hook angle, not just behind minions.",
            "Use E to punish missed hook; hold Q for disengage or confirmed root.",
            "Ward lane brush early so Nautilus cannot reset fog pressure.",
        ],
        "mid": [
            "Move first only when bot wave is pushed and river is warded.",
            "Before dragon, place vision from range and avoid face-checking support fog.",
        ],
        "late": "Poke before objectives and save Q for the first engage target, not max-range fishing.",
        "items": [
            ("Mikael's Blessing", "cleanse hook follow-up when your carry is the win condition."),
            ("Zhonya's Hourglass", "survive all-in if Nautilus can reach you."),
        ],
    },
}


CHAMPION_PLANS: dict[str, dict[str, object]] = {
    "Jinx": {
        "identity": "scaling reset marksman",
        "lane": [
            "Keep the wave playable; losing HP is worse than missing one caster.",
            "Use rockets for safe last-hit or short poke, then return to minigun for DPS.",
        ],
        "mid": [
            "Take mid farm after lane and rotate only with support vision.",
            "Do not start objective fights from fog; arrive through controlled space.",
        ],
        "late": "Front-to-back until passive reset, then convert the fight with movement speed.",
        "items": [
            ("Infinity Edge", "core crit damage spike."),
            ("Phantom Dancer", "safer DPS uptime and chase after reset."),
        ],
    },
    "Caitlyn": {
        "identity": "lane pressure siege marksman",
        "lane": [
            "Push first waves, trap tower exits, and convert range into plates.",
            "Do not overstep without net when enemy engage cooldowns are available.",
        ],
        "mid": [
            "Use traps to control objective entrances before the enemy arrives.",
            "Siege mid with support vision instead of taking isolated side fights.",
        ],
        "late": "Trap choke points first, then hit whoever walks into your zone.",
        "items": [
            ("Infinity Edge", "crit breakpoint for headshot damage."),
            ("Rapid Firecannon", "safer siege and first-hit range."),
        ],
    },
    "Seraphine": {
        "identity": "scaling enchanter/teamfight mage",
        "lane": [
            "Trade around passive range and keep E/Q for follow-up, not blind spam.",
            "Preserve HP until W can turn extended trades.",
        ],
        "mid": [
            "Group before objectives; Seraphine value drops when arriving late.",
            "Use E/R after ally CC or enemy engage, not before they commit.",
        ],
        "late": "Play behind frontline and chain R through grouped enemies or allies.",
        "items": [
            ("Moonstone Renewer", "extended fight healing value."),
            ("Locket of the Iron Solari", "answer first engage burst when needed."),
        ],
    },
}


def parse_counter_context(matchup_data: str) -> dict[str, object]:
    games = _search_int(r"Data source:\s*(\d+)", matchup_data)
    win_rate = _search_float(r"Win rate:\s*([\d.]+)%", matchup_data)
    data_label = _search_text(r"Win rate:\s*[\d.]+%\s*\(([^)]+)\)", matchup_data)
    best_items_raw = _search_text(r"Best items in winning games:\s*(.+)", matchup_data)
    best_items = [item.strip() for item in best_items_raw.split(",") if item.strip()] if best_items_raw else []
    return {
        "games": games,
        "win_rate": win_rate,
        "data_label": data_label or "Directional",
        "best_items": best_items,
    }


def build_counter_plan(
    your_champ: str,
    your_pos: str,
    enemy_champ: str,
    matchup_data: str,
) -> str:
    context = parse_counter_context(matchup_data)
    pair = PAIR_PLANS.get((your_champ, your_pos, enemy_champ))
    base = CHAMPION_PLANS.get(your_champ, {})

    matchup_read = _matchup_read(your_champ, enemy_champ, context, pair, base)
    lane_lines = list(pair.get("lane", []) if pair else base.get("lane", []))
    mid_lines = list(pair.get("mid", []) if pair else base.get("mid", []))
    late_text = str(pair.get("late") if pair else base.get("late", "Play fights around your champion identity and known enemy threat windows."))
    item_lines = _item_plan(context["best_items"], pair, base)

    if not lane_lines:
        lane_lines = [
            f"Identify {enemy_champ}'s main cooldown before trading.",
            "Trade only when wave state lets you leave without losing tempo.",
        ]
    if not mid_lines:
        mid_lines = [
            "Move after wave priority, not while a stacked wave is dying.",
            "Set objective vision before the enemy controls river entrances.",
        ]

    return (
        "MATCHUP READ\n"
        f"{matchup_read}\n\n"
        "LANE PLAN\n"
        + "\n".join(f"- {line}" for line in lane_lines[:3])
        + "\n\nMID GAME\n"
        + "\n".join(f"- {line}" for line in mid_lines[:2])
        + "\n\nLATE GAME\n"
        f"{late_text}\n\n"
        "ITEM PLAN\n"
        + "\n".join(f"- {item} - {reason}" for item, reason in item_lines[:2])
    )


def _item_plan(best_items: list[str], pair: dict[str, object] | None, base: dict[str, object]) -> list[tuple[str, str]]:
    planned = list(pair.get("items", []) if pair else base.get("items", []))
    filtered = [item for item in best_items if item not in LOW_VALUE_ITEM_NAMES]
    if filtered:
        data_items = ", ".join(filtered[:3])
        planned.append((data_items, "appears most often in winning Master+ samples; treat as reference, not a rule."))
    return planned or [("Core item", "align with champion spike."), ("Defensive option", "buy only if enemy threat pattern demands it.")]


def _matchup_read(
    your_champ: str,
    enemy_champ: str,
    context: dict[str, object],
    pair: dict[str, object] | None,
    base: dict[str, object],
) -> str:
    games = context["games"]
    win_rate = context["win_rate"]
    sample_note = f"{games} Master+ games" if games else "available Master+ sample"
    if win_rate is not None:
        data = f"Data says {win_rate:.1f}% over {sample_note}"
    else:
        data = f"Use {sample_note} as directional context"
    if pair:
        return f"{data}, but the practical read is: {pair['matchup']}"
    identity = base.get("identity", "champion identity")
    return f"{data}; play the lane around {your_champ}'s {identity} while denying {enemy_champ}'s first reliable trade window."


def _search_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text or "")
    return int(match.group(1)) if match else None


def _search_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text or "")
    return float(match.group(1)) if match else None


def _search_text(pattern: str, text: str) -> str:
    match = re.search(pattern, text or "")
    return match.group(1).strip() if match else ""
