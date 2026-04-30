"""Contextual champion coaching rules.

Rules are stored in data/champion_rules.json so the app can be expanded without
editing page code. Runtime matching is deterministic; agents can later be used
offline to draft more rules into the same schema.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


RULES_PATH = Path("data/champion_rules.json")

THREAT_CHAMPIONS: dict[str, set[str]] = {
    "burst": {
        "Zed", "Talon", "Katarina", "Syndra", "Veigar", "Annie", "LeBlanc",
        "Fizz", "Akali", "Diana", "Ekko", "Lux", "Orianna", "Xerath",
        "Viktor", "Hwei", "Lucian", "Pantheon", "Viego", "Brand", "Draven",
        "Rengar", "Kha'Zix", "KhaZix", "Qiyana", "Nocturne", "Samira",
    },
    "tank": {
        "Malphite", "Ornn", "Sion", "Cho'Gath", "Leona", "Nautilus",
        "Amumu", "Galio", "Maokai", "Sejuani", "Poppy", "Rell", "Zac",
    },
    "cc": {
        "Leona", "Nautilus", "Amumu", "Lissandra", "Morgana", "Sejuani",
        "Rell", "Blitzcrank", "Thresh", "Zac", "Malzahar", "Warwick",
        "Pantheon", "Hwei", "Maokai", "Galio", "Ornn", "Poppy",
    },
    "engage": {
        "Zac", "Malphite", "Leona", "Nautilus", "Rell", "Amumu", "Pantheon",
        "Vi", "JarvanIV", "Jarvan IV", "Nocturne", "Hecarim", "Rakan", "Alistar",
    },
    "heal": {"Soraka", "Vladimir", "Aatrox", "Yuumi", "Nami", "Sona", "Seraphine"},
}

ITEM_TAGS: dict[str, set[str]] = {
    "locket": {"Locket of the Iron Solari"},
    "mikael": {"Mikael's Blessing"},
    "anti_heal": {"Morellonomicon", "Oblivion Orb", "Chemtech Putrifier", "Mortal Reminder", "Thornmail"},
    "zhonya": {"Zhonya's Hourglass"},
    "banshee": {"Banshee's Veil"},
    "ldr": {"Lord Dominik's Regards"},
    "void_staff": {"Void Staff"},
    "anti_burst": {
        "Locket of the Iron Solari", "Zhonya's Hourglass", "Banshee's Veil",
        "Seraph's Embrace", "Crown of the Shattered Queen",
    },
}


@lru_cache(maxsize=1)
def load_champion_rules() -> dict[str, list[dict]]:
    if not RULES_PATH.exists():
        return {}
    with RULES_PATH.open() as f:
        return json.load(f)


def get_enemy_threats(champions: list[str]) -> dict[str, list[str]]:
    """Return threat tag -> enemy champions matching that tag."""
    threats: dict[str, list[str]] = {tag: [] for tag in THREAT_CHAMPIONS}
    lower_lookup = {champ.lower(): champ for champ in champions}
    for tag, tag_champs in THREAT_CHAMPIONS.items():
        tagged = []
        for champ in tag_champs:
            original = lower_lookup.get(champ.lower())
            if original and original not in tagged:
                tagged.append(original)
        threats[tag] = tagged
    return threats


def get_item_tags(item_names: list[str]) -> set[str]:
    """Map built item names into normalized item tags."""
    built = set(item_names)
    return {
        tag
        for tag, names in ITEM_TAGS.items()
        if built.intersection(names)
    }


def has_item_tag(item_names: list[str], tag: str) -> bool:
    return bool(set(item_names).intersection(ITEM_TAGS.get(tag, set())))


def _rule_score(
    rule: dict,
    enemy_tags: set[str],
    item_tags: set[str],
    ally_comp_type: str,
    enemy_comp_type: str,
) -> int:
    score = 0
    required_enemy_tags = set(rule.get("enemy_tags", []))
    required_item_tags = set(rule.get("item_tags", []))
    if not required_enemy_tags.issubset(enemy_tags):
        return -1
    if not required_item_tags.issubset(item_tags):
        return -1
    if rule.get("ally_comp") and rule["ally_comp"] != ally_comp_type:
        return -1
    if rule.get("enemy_comp") and rule["enemy_comp"] != enemy_comp_type:
        return -1
    score += len(required_enemy_tags) * 3
    score += len(required_item_tags) * 4
    score += 2 if rule.get("ally_comp") else 0
    score += 2 if rule.get("enemy_comp") else 0
    return score


def get_contextual_champion_tips(
    champion: str,
    phase: str,
    *,
    ally_comp_type: str = "",
    enemy_comp_type: str = "",
    enemy_tags: set[str] | None = None,
    item_tags: set[str] | None = None,
    limit: int = 2,
) -> list[str]:
    """Return the best matching coaching tips for champion + game context."""
    rules = load_champion_rules().get(champion, [])
    enemy_tags = enemy_tags or set()
    item_tags = item_tags or set()
    scored: list[tuple[int, str]] = []
    for rule in rules:
        if rule.get("phase") != phase:
            continue
        score = _rule_score(rule, enemy_tags, item_tags, ally_comp_type, enemy_comp_type)
        if score >= 0:
            scored.append((score, rule["text"]))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    tips = []
    for _, text in scored:
        if text not in tips:
            tips.append(text)
        if len(tips) >= limit:
            break
    return tips
