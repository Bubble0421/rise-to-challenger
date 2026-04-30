"""
Comp classification and game plan generation — purely rule-based, no LLM.
"""
from __future__ import annotations

COMP_TYPES: dict[str, list[str]] = {
    "engage":     ["Malphite", "Amumu", "Leona", "Nautilus", "Vi", "Jarvan IV",
                   "Jarvan", "Rell", "Sejuani", "Alistar", "Rakan", "Galio",
                   "Zac", "Rammus", "Hecarim"],
    "poke":       ["Jayce", "Lux", "Ezreal", "Karma", "Zoe", "Nidalee",
                   "Xerath", "Varus", "Corki", "Ziggs", "Heimer",
                   "Heimerdinger", "Vel'Koz", "Velkoz"],
    "splitpush":  ["Fiora", "Tryndamere", "Jax", "Camille", "Yorick",
                   "Nasus", "Illaoi", "Garen", "Darius", "Urgot"],
    "teamfight":  ["Orianna", "Miss Fortune", "MissFortune", "Yasuo", "Yone",
                   "Rumble", "Kennen", "Amumu", "Sona", "Seraphine",
                   "Karthus", "Kog'Maw", "KogMaw", "Fiddlesticks", "Smolder",
                   "Mel", "Azir", "Viktor", "Hwei"],
    "protect":    ["Lulu", "Janna", "Soraka", "Yuumi", "Renata", "Karma",
                   "Sona", "Seraphine", "Milio", "Taric"],
    "assassin":   ["Zed", "Talon", "Katarina", "Akali", "Kha'Zix", "KhaZix",
                   "Qiyana", "LeBlanc", "Ekko", "Fizz", "Pyke", "Rengar"],
}

FIGHT_CORE_ROLES: dict[str, str] = {
    "Seraphine": "shield/heal reset + AoE CC",
    "Sona": "aura scaling + teamfight sustain",
    "Smolder": "late-game AoE damage",
    "Fiddlesticks": "flank engage + AoE fear",
    "Mel": "mid control + reflected burst",
    "Hwei": "zone control + AoE teamfight",
    "Orianna": "ball delivery + wombo engage",
    "Azir": "DPS zone + shuffle threat",
    "Viktor": "zone control + scaling DPS",
    "Vladimir": "scaling flank burst + backline threat",
    "Miss Fortune": "AoE ult damage",
    "Rumble": "Equalizer zone control",
    "Kennen": "flank stun engage",
    "Amumu": "AoE lockdown engage",
    "Yasuo": "knock-up follow-up carry",
    "Yone": "backline access + AoE engage",
    "Karthus": "global damage + death-zone DPS",
    "Kog'Maw": "protected hypercarry DPS",
    "KogMaw": "protected hypercarry DPS",
    "Lulu": "hypercarry protection",
    "Janna": "disengage + peel",
    "Soraka": "sustain engine",
    "Yuumi": "attach scaling + carry amplify",
    "Renata": "anti-engage + bailout",
    "Karma": "shield speed + poke setup",
    "Milio": "range amplify + cleanse",
    "Taric": "invulnerability + counter-engage",
    "Malphite": "primary engage",
    "Leona": "lockdown engage",
    "Nautilus": "pick engage + CC chain",
    "Rell": "AoE engage",
    "Alistar": "engage/disengage frontline",
    "Rakan": "mobile charm engage",
    "Galio": "follow-up engage + protection",
    "Sejuani": "frontline pick engage",
    "Vi": "single-target lockdown",
    "Jarvan IV": "terrain engage",
    "Jarvan": "terrain engage",
    "Zac": "long-range engage",
    "Hecarim": "backline fear engage",
}

# Which comp types beat which
_COUNTER_MAP: dict[str, str] = {
    "engage":    "poke",       # poke beats engage
    "poke":      "assassin",   # assassin beats poke
    "assassin":  "protect",    # protect beats assassin
    "protect":   "teamfight",  # teamfight beats protect
    "teamfight": "splitpush",  # splitpush beats teamfight
    "splitpush": "engage",     # engage beats splitpush
}

_GAME_PLANS: dict[tuple[str, str], dict[str, str]] = {
    # (ally_type, position)
    ("engage", "UTILITY"):    {
        "lane":      "Play aggressive at level 2-3 — Leona/Nautilus power spike. All-in with ADC.",
        "mid_game":  "Roam mid at level 6. Your ult enables picks anywhere on the map.",
        "teamfight": "Initiate from fog — hard engage before enemy poke can chip HP.",
        "win_condition": "Force 5v5 teamfights before enemy pokes your carries below 70% HP.",
    },
    ("engage", "JUNGLE"):     {
        "lane":      "Gank early — your CC enables kills at level 2. Prioritize bot side.",
        "mid_game":  "Secure dragon with engage chain. Hard engage on grouped enemies.",
        "teamfight": "Flank from river — single target into backline then body block.",
        "win_condition": "Win teamfights through engage advantage. Secure every major objective.",
    },
    ("poke", "UTILITY"):      {
        "lane":      "Harass at max range — deny lane CS. Save CC for disengage, not engage.",
        "mid_game":  "Poke before baron — reduce HP before fight starts.",
        "teamfight": "Stay behind frontline. Zone with Q/E, don't walk into engage range.",
        "win_condition": "Poke enemies to 40% HP, then convert with 1-2 picks.",
    },
    ("poke", "MIDDLE"):       {
        "lane":      "Push wave then poke — shove first, harass second.",
        "mid_game":  "Control river with vision, poke from brushes pre-objective.",
        "teamfight": "Long range poke before fight — stay outside engage range.",
        "win_condition": "Force fights when enemies are poked low. Scale into split threat.",
    },
    ("teamfight", "BOTTOM"):  {
        "lane":      "Farm safely — your power spike is post-2 items. Avoid early all-ins.",
        "mid_game":  "Group at 2 items. Your AoE shreds grouped enemies.",
        "teamfight": "Position center — maximize AoE. Trust your frontline to peel.",
        "win_condition": "Win grouped 5v5 teamfights. Do not split or fight in small skirmishes.",
    },
    ("protect", "UTILITY"):   {
        "lane":      "Shield ADC during all trades. Play reactive — answer aggression, don't create it.",
        "mid_game":  "Stay glued to hypercarry. Deny assassin access with peeling spells.",
        "teamfight": "Peel backline constantly — ignore their frontline entirely.",
        "win_condition": "Keep ADC alive to 3 items. One clean teamfight wins the game.",
    },
    ("assassin", "MIDDLE"):   {
        "lane":      "Shove wave then roam — kills create more gold than farm.",
        "mid_game":  "Pick off isolated targets. Avoid 5v5 — look for 1v1 picks.",
        "teamfight": "Wait for frontline to engage, then flank backline carry.",
        "win_condition": "Snowball early kills into tower dives. End before late game.",
    },
    ("splitpush", "TOP"):     {
        "lane":      "Win lane 1v1 — deny plates. Set TP for team fights or deny TP for split.",
        "mid_game":  "Split side lane while team contests objectives. Apply constant pressure.",
        "teamfight": "Join teamfight only via TP or if outnumbered. Otherwise, keep splitting.",
        "win_condition": "Create 1-3-1 or 1-4 split. Win by forcing impossible decisions.",
    },
}

_DEFAULT_PLAN = {
    "lane":      "Play position-appropriate early game — CS efficiently and avoid unnecessary risks.",
    "mid_game":  "Group with team at objective timers. Maintain vision around major objectives.",
    "teamfight": "Stay in position — don't overcommit to damage at the cost of survival.",
    "win_condition": "Execute your comp's win condition — scale or snowball depending on match state.",
}


def classify_comp(champions: list[str]) -> str:
    """Return the dominant comp type for a list of champions."""
    counts: dict[str, int] = {t: 0 for t in COMP_TYPES}
    for champ in champions:
        champ_lower = champ.lower()
        for comp_type, champ_list in COMP_TYPES.items():
            if any(c.lower() == champ_lower for c in champ_list):
                counts[comp_type] += 1
                break
    top = max(counts, key=counts.get)
    return top if counts[top] > 0 else "teamfight"


def get_team_identity(champions: list[str], player_champion: str, position: str) -> dict[str, str]:
    """Describe team identity without assigning every player the same comp job."""
    normalized = {champ.lower(): champ for champ in champions}

    def champs_for(comp_type: str) -> list[str]:
        known = {champ.lower() for champ in COMP_TYPES.get(comp_type, [])}
        return [display for lower, display in normalized.items() if lower in known]

    side_carriers = champs_for("splitpush")
    fight_core = []
    for comp_type in ("teamfight", "protect", "engage"):
        for champ in champs_for(comp_type):
            if champ not in fight_core:
                fight_core.append(champ)
    fight_core_detail = [
        f"{champ} - {FIGHT_CORE_ROLES.get(champ, 'teamfight utility')}"
        for champ in fight_core
    ]

    poke_core = champs_for("poke")
    assassins = champs_for("assassin")

    if fight_core and side_carriers:
        primary = "Scaling teamfight with side-lane pressure"
    elif len(fight_core) >= 2:
        primary = "Grouped teamfight scaling"
    elif len(side_carriers) >= 2:
        primary = "Side-lane pressure"
    elif poke_core:
        primary = "Poke and objective setup"
    elif assassins:
        primary = "Pick and snowball"
    else:
        primary = "Balanced front-to-back"

    player_is_side = player_champion in side_carriers and position == "TOP"
    player_is_fight_core = player_champion in fight_core
    if player_is_side:
        player_job = "Own side lane, draw pressure, join only for high-value objective timers."
    elif position == "MIDDLE":
        player_job = "Hold mid economy, control river move windows, and join controlled objective fights."
    elif position == "JUNGLE":
        player_job = "Turn lane priority into objective setup and protect the first move into river."
    elif position == "BOTTOM":
        player_job = "Preserve item timing, hit front-to-back fights, and avoid low-value early deaths."
    elif position == "UTILITY":
        player_job = "Create vision windows, protect carry access, and decide when fights can start."
    elif player_is_fight_core:
        player_job = "Arrive to grouped fights with key cooldowns available."
    else:
        player_job = "Serve the team's primary win condition rather than copying another role's job."

    return {
        "primary": primary,
        "side_carrier": ", ".join(side_carriers) if side_carriers else "None",
        "fight_core": ", ".join(fight_core) if fight_core else "None",
        "fight_core_detail": "; ".join(fight_core_detail) if fight_core_detail else "None",
        "player_job": player_job,
    }


def get_game_plan(
    ally_comp_type: str,
    enemy_comp_type: str,
    position: str,
    champion: str,
) -> dict[str, str]:
    """Return a 4-key game plan dict for the given comp + position."""
    plan = _GAME_PLANS.get((ally_comp_type, position))
    if plan:
        return plan
    # Fallback: try generic comp plan
    for pos in ("UTILITY", "JUNGLE", "MIDDLE", "TOP", "BOTTOM"):
        plan = _GAME_PLANS.get((ally_comp_type, pos))
        if plan:
            return plan
    return _DEFAULT_PLAN


def comp_label(comp_type: str) -> str:
    return {
        "engage": "Engage Comp",
        "poke": "Poke Comp",
        "splitpush": "Split Push",
        "teamfight": "Teamfight Comp",
        "protect": "Protect Comp",
        "assassin": "Assassin Comp",
    }.get(comp_type, comp_type.title())
