"""Lightweight coaching knowledge injected into LLM prompts.

This is intentionally small: archetype rules scale better than maintaining a
full encyclopedia for every champion. Champion notes are added only for champs
where generic advice is easy to get wrong.
"""
from __future__ import annotations


ASSASSIN_THREATS = {
    "Akali", "Zed", "Talon", "Katarina", "Qiyana", "KhaZix", "Kha'Zix",
    "LeBlanc", "Fizz", "Ekko", "Rengar", "Nocturne", "Viego", "Diana",
}
HARD_ENGAGE_THREATS = {
    "Leona", "Nautilus", "Rell", "Alistar", "Malphite", "Amumu", "Vi",
    "JarvanIV", "Jarvan IV", "Hecarim", "Rakan", "Zac", "Sejuani",
}
CC_THREATS = {
    "Leona", "Nautilus", "Morgana", "Lissandra", "Malzahar", "Thresh",
    "Blitzcrank", "Rell", "Sejuani", "Amumu", "Maokai", "Galio",
}


CHAMPION_KIT_PRINCIPLES: dict[str, list[str]] = {
    "Lux": [
        "Lux has no mobility after Flash; do not describe her as mobile.",
        "Use E to check brush before walking into fog when vision is unsafe.",
        "Hold Q for divers or assassins if enemy flank threat can reach you.",
        "Play behind frontline and look for pick/poke angles before objectives.",
    ],
    "Seraphine": [
        "Seraphine is strongest from behind allies, chaining E/R through grouped fights.",
        "W is highest value after enemy engage when multiple allies can receive shield/heal.",
        "Avoid solo river entry; she needs teammates nearby when setting vision.",
    ],
    "Jinx": [
        "Jinx wants front-to-back fights and reset windows, not early isolated skirmishes.",
        "Respect assassin/flank access until traps, peel, or summoners are available.",
    ],
    "Caitlyn": [
        "Caitlyn wins through range, traps, turret pressure, and objective setup before fights.",
        "Trap placement around choke points matters more than diving into fights.",
    ],
}


ROLE_PRINCIPLES: dict[str, list[str]] = {
    "UTILITY": [
        "Support review should prioritize vision timing, death risk while warding, peel, and objective setup over raw damage.",
        "When entering fog, the coaching correction should be to move with teammates or use long-range spells first, not to face-check.",
    ],
    "JUNGLE": [
        "Jungle review should prioritize tempo, KP, objective setup, and death timing over raw damage.",
    ],
    "BOTTOM": [
        "ADC review should prioritize damage uptime, deaths, first item timing, and front-to-back positioning.",
    ],
    "MIDDLE": [
        "Mid review should connect lane control to roam/objective access and damage responsibility.",
    ],
    "TOP": [
        "Top review should connect lane state to side pressure, teamfight role, and death discipline.",
    ],
}


THREAT_PRINCIPLES: dict[str, list[str]] = {
    "assassin": [
        "Against assassins, the correction is spacing, holding hard CC/peel, and considering Zhonya's/Banshee's when deaths or build gaps support it.",
        "Do not claim the assassin killed the player unless death data explicitly supports it; phrase as threat pressure or likely risk.",
    ],
    "hard_engage": [
        "Against hard engage, vision should be set with teammates before objectives, using long-range spells to check unsafe brush.",
        "Defensive support items like Locket are valid when enemy win condition is first-combo engage burst.",
    ],
    "cc_chain": [
        "Against heavy CC, Mikael's/Cleanse/Banshee's style answers matter only if the player or carry is being locked down.",
    ],
}


def _names_present(match_data: str, names: set[str]) -> list[str]:
    return sorted(name for name in names if name.lower() in match_data.lower())


def build_knowledge_context(champion: str, position: str, match_data: str) -> str:
    lines: list[str] = []
    role_notes = ROLE_PRINCIPLES.get(position, [])
    champ_notes = CHAMPION_KIT_PRINCIPLES.get(champion, [])

    if role_notes:
        lines.append(f"Role principles for {position}:")
        lines.extend(f"- {note}" for note in role_notes)
    if champ_notes:
        lines.append(f"Known kit principles for {champion}:")
        lines.extend(f"- {note}" for note in champ_notes)

    assassin_hits = _names_present(match_data, ASSASSIN_THREATS)
    engage_hits = _names_present(match_data, HARD_ENGAGE_THREATS)
    cc_hits = _names_present(match_data, CC_THREATS)

    if assassin_hits:
        lines.append(f"Threat archetype: assassin/flank pressure ({', '.join(assassin_hits[:3])})")
        lines.extend(f"- {note}" for note in THREAT_PRINCIPLES["assassin"])
    if engage_hits:
        lines.append(f"Threat archetype: hard engage ({', '.join(engage_hits[:3])})")
        lines.extend(f"- {note}" for note in THREAT_PRINCIPLES["hard_engage"])
    if cc_hits:
        lines.append(f"Threat archetype: CC chain ({', '.join(cc_hits[:3])})")
        lines.extend(f"- {note}" for note in THREAT_PRINCIPLES["cc_chain"])

    if not lines:
        return "No champion-specific notes. Use only role, comp, and match metrics."
    return "\n".join(lines)
