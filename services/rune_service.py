"""
Rune and summoner spell evaluation — DDragon lookups + comp-aware coaching.
Uses a coaching voice (optimal / situational / unusual), not pass/fail.
"""
from __future__ import annotations
import requests
from functools import lru_cache

from core.config import PATCH

# ─── DDragon data loaders ──────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_runes() -> dict[int, str]:
    try:
        url = f"https://ddragon.leagueoflegends.com/cdn/{PATCH}/data/en_US/runesReforged.json"
        trees = requests.get(url, timeout=5).json()
        result = {}
        for tree in trees:
            for slot in tree.get("slots", []):
                for rune in slot.get("runes", []):
                    result[rune["id"]] = rune["name"]
        return result
    except Exception:
        return {}


@lru_cache(maxsize=1)
def _load_spells() -> dict[int, str]:
    try:
        url = f"https://ddragon.leagueoflegends.com/cdn/{PATCH}/data/en_US/summoner.json"
        data = requests.get(url, timeout=5).json()["data"]
        return {int(v["key"]): v["name"] for v in data.values()}
    except Exception:
        return {}


def get_rune_name(rune_id: int) -> str:
    return _load_runes().get(rune_id, f"Rune #{rune_id}")


def get_spell_name(spell_id: int) -> str:
    return _load_spells().get(spell_id, f"Spell #{spell_id}")


# ─── Keystone data: pick rate + comp context ──────────────────────────────────
# keystone_name → {position → {pick_rate, best_comps, works_when, skip_when}}
# Each keystone has ALL its positions in one dict (no duplicate keys).

_KEYSTONE_DATA: dict[str, dict[str, dict]] = {
    "Summon Aery": {
        "UTILITY": {
            "pick_rate": 72, "best_comps": ["poke", "protect"],
            "works_when": "You're playing an enchanter or poke support (Lulu, Karma, Janna, Soraka)",
            "skip_when": "Your role is to engage or your team needs hard CC",
        },
        "MIDDLE": {
            "pick_rate": 8, "best_comps": ["poke"],
            "works_when": "Sustained poke mage that procs Aery on every ability",
            "skip_when": "Burst mage or assassin — Aery is outclassed by Electrocute burst",
        },
    },
    "Arcane Comet": {
        "UTILITY": {
            "pick_rate": 15, "best_comps": ["poke"],
            "works_when": "Long-range poke with reliable CC to proc comet (Xerath, Vel'Koz, Lux)",
            "skip_when": "Enemy is mobile — they'll dodge comet easily",
        },
        "MIDDLE": {
            "pick_rate": 15, "best_comps": ["poke"],
            "works_when": "Long-range poke mage (Ziggs, Xerath, Vel'Koz) with reliable poke windows",
            "skip_when": "Mobile enemies that dodge skillshots",
        },
    },
    "Glacial Augment": {
        "UTILITY": {
            "pick_rate": 8, "best_comps": ["engage", "poke"],
            "works_when": "Itemizing Everfrost or Zhonya's; coordinating with engage team",
            "skip_when": "Standard poke or enchanter builds",
        },
    },
    "Guardian": {
        "UTILITY": {
            "pick_rate": 6, "best_comps": ["protect"],
            "works_when": "Dedicated protect-the-carry with laning partner who dives in (Kog'Maw, Jinx)",
            "skip_when": "Your ADC is a self-sufficient carry (Tristana, Ezreal)",
        },
    },
    "Aftershock": {
        "UTILITY": {
            "pick_rate": 5, "best_comps": ["engage"],
            "works_when": "Tank engage support with reliable CC (Nautilus, Leona, Rell, Blitzcrank)",
            "skip_when": "You have no reliable CC to proc Aftershock",
        },
    },
    "Dark Harvest": {
        "UTILITY": {
            "pick_rate": 4, "best_comps": ["poke", "assassin"],
            "works_when": "Full AP damage build (Luden's, Shadowflame) vs squishy enemy team",
            "skip_when": "Enchanter build or tankier enemy team — stacks won't proc reliably",
        },
        "MIDDLE": {
            "pick_rate": 12, "best_comps": ["assassin"],
            "works_when": "Snowball-focused assassin (Talon, Katarina, Zed) in killing games",
            "skip_when": "Even or defensive games — stacks won't accumulate",
        },
        "JUNGLE": {
            "pick_rate": 15, "best_comps": ["assassin"],
            "works_when": "Snowball jungler (Kha'Zix, Kayn) in high-kill games — stacks = late-game damage",
            "skip_when": "Balanced games or tank jungler — stacks won't accumulate safely",
        },
    },
    "Lethal Tempo": {
        "BOTTOM": {
            "pick_rate": 35, "best_comps": ["teamfight"],
            "works_when": "Extended teamfight ADC (Jinx, Kog'Maw, Aphelios) with frontline protection",
            "skip_when": "Poke-heavy or dueling-focused ADC",
        },
    },
    "Fleet Footwork": {
        "BOTTOM": {
            "pick_rate": 28, "best_comps": ["poke", "teamfight"],
            "works_when": "Lane sustain pick (Ezreal, Sivir) or slippery ADC that needs mobility",
            "skip_when": "Your ADC has strong early game all-in potential",
        },
    },
    "Press the Attack": {
        "BOTTOM": {
            "pick_rate": 22, "best_comps": ["teamfight", "engage"],
            "works_when": "Early skirmish ADC (Draven, Caitlyn) with an aggressive support",
            "skip_when": "Lane is poke-focused or you're playing for late-game scaling",
        },
    },
    "Conqueror": {
        "BOTTOM": {
            "pick_rate": 8, "best_comps": ["teamfight"],
            "works_when": "On-hit/hybrid ADC (Kog'Maw, Varus, Smolder) in extended fights",
            "skip_when": "Standard crit ADC — Conqueror doesn't stack fast enough",
        },
        "MIDDLE": {
            "pick_rate": 25, "best_comps": ["teamfight", "engage"],
            "works_when": "Sustained fighter mid (Viktor, Sylas, Irelia) in long teamfights",
            "skip_when": "Burst combo mage — you win before Conqueror stacks",
        },
        "TOP": {
            "pick_rate": 45, "best_comps": ["teamfight", "engage", "splitpush"],
            "works_when": "Sustained fighter (Darius, Garen, Fiora, Camille) in extended fights",
            "skip_when": "Tank or poke top — Conqueror stacking requires sustained fighting",
        },
        "JUNGLE": {
            "pick_rate": 38, "best_comps": ["teamfight", "engage"],
            "works_when": "Sustained fighter jungle (Hecarim, Vi, Jarvan) with long teamfight presence",
            "skip_when": "Burst assassin that finishes fights in one rotation",
        },
    },
    "Electrocute": {
        "MIDDLE": {
            "pick_rate": 30, "best_comps": ["assassin", "poke"],
            "works_when": "Burst mage or assassin with 3-hit combo (Syndra, Zoe, Talon, Zed)",
            "skip_when": "Sustained teamfight champion without reliable burst window",
        },
        "JUNGLE": {
            "pick_rate": 22, "best_comps": ["assassin"],
            "works_when": "Burst assassin ganker (Kha'Zix, Evelynn, Rengar) landing quick kill combos",
            "skip_when": "Tank jungler or sustained teamfighter",
        },
    },
    "Phase Rush": {
        "MIDDLE": {
            "pick_rate": 18, "best_comps": ["poke", "teamfight"],
            "works_when": "Poke mage needing kite mobility (Cassiopeia, Orianna) or slippery assassin",
            "skip_when": "Your kit already provides mobility or you fight from long range",
        },
        "TOP": {
            "pick_rate": 12, "best_comps": ["poke", "splitpush"],
            "works_when": "Kiting or chasing champion (Kennen, Kayle, Jayce) that needs speed",
            "skip_when": "Tanky melee fighters that engage rather than disengage",
        },
    },
    "Grasp of the Undying": {
        "TOP": {
            "pick_rate": 25, "best_comps": ["engage", "teamfight"],
            "works_when": "Tank or auto-attack melee (Maokai, Ornn, Garen) for HP scaling",
            "skip_when": "Ability-based fighters that don't auto reliably in lane",
        },
    },
    "Predator": {
        "JUNGLE": {
            "pick_rate": 10, "best_comps": ["engage"],
            "works_when": "Engage or gank-heavy jungler (Hecarim, Rammus) needing instant engage",
            "skip_when": "Sustained fighter or objective-focused clear jungler",
        },
    },
    "Hail of Blades": {
        "BOTTOM": {
            "pick_rate": 12, "best_comps": ["assassin", "teamfight"],
            "works_when": "Attack-speed burst ADC (Miss Fortune, Draven, Vayne) looking for quick all-in windows",
            "skip_when": "Late-scaling crit ADC that relies on sustained DPS rather than burst autos",
        },
        "JUNGLE": {
            "pick_rate": 8, "best_comps": ["assassin"],
            "works_when": "On-hit or burst assassin jungler (Rengar, Kha'Zix, Vi) that combos in short trades",
            "skip_when": "Sustained fighter or objective-focused jungler that farms through fights",
        },
        "TOP": {
            "pick_rate": 6, "best_comps": ["assassin", "splitpush"],
            "works_when": "Short-trade auto-attack top (Darius, Vayne top, Urgot) opening with burst autos",
            "skip_when": "Long-fight sustained champion — Conqueror outscales after the first few autos",
        },
    },
    "First Strike": {
        "MIDDLE": {
            "pick_rate": 14, "best_comps": ["poke"],
            "works_when": "Poke-first champion (Ezreal mid, Corki, Jayce) that engages from range before the enemy reacts",
            "skip_when": "Reactive or engage champion — you won't reliably land the first hit",
        },
        "JUNGLE": {
            "pick_rate": 8, "best_comps": ["poke", "assassin"],
            "works_when": "Invade or skirmish-heavy jungler (Graves, Kindred) that consistently initiates fights",
            "skip_when": "Reactive ganker or tank jungler that takes hits before dealing damage",
        },
        "BOTTOM": {
            "pick_rate": 10, "best_comps": ["poke"],
            "works_when": "Long-range poke ADC (Ezreal, Corki, Varus) that pokes before trading",
            "skip_when": "All-in or short-range ADC — you'll lose First Strike procs in early trades",
        },
    },
    "Lethal Tempo": {
        "JUNGLE": {
            "pick_rate": 10, "best_comps": ["teamfight"],
            "works_when": "On-hit auto-attack jungler (Kindred, Master Yi, Warwick) in extended fights",
            "skip_when": "Burst assassin or engage jungler that doesn't rely on sustained auto attacks",
        },
        "TOP": {
            "pick_rate": 15, "best_comps": ["teamfight", "splitpush"],
            "works_when": "Auto-attack melee fighter (Nasus, Garen, Tryndamere) that stacks attack speed in extended duels",
            "skip_when": "Ability-based burst top or tank that doesn't auto-attack frequently",
        },
    },
    "Fleet Footwork": {
        "UTILITY": {
            "pick_rate": 8, "best_comps": ["poke", "protect"],
            "works_when": "Heal-on-hit support (Sona, Nami) needing lane sustain or kite mobility in skirmishes",
            "skip_when": "Engage or damage support — Fleet healing is negligible compared to aggressive keystone damage",
        },
        "TOP": {
            "pick_rate": 10, "best_comps": ["poke", "splitpush"],
            "works_when": "Kite-heavy or ranged top (Kayle, Quinn, Jayce) relying on safe harass and mobility",
            "skip_when": "Melee fighter that needs damage output in trades rather than movement speed",
        },
    },
    "Electrocute": {
        "UTILITY": {
            "pick_rate": 12, "best_comps": ["assassin", "poke"],
            "works_when": "Damage-focused support (Brand, Zyra, Vel'Koz) that procs 3-hit combos for kill pressure",
            "skip_when": "Enchanter or tank support — you don't reliably proc Electrocute in lane",
        },
    },
}

# ─── Summoner spell coaching ──────────────────────────────────────────────────

_SPELL_COACHING: dict[str, dict[str, dict]] = {
    "UTILITY": {
        "engage": {
            "recommended": "Exhaust",
            "pick_rate_recommended": 65,
            "avoid": "Ignite",
            "reason": "In engage comps, your job is protecting carries after the engage. Exhaust negates the burst that follows. Challengers run Exhaust in ~65% of engage comp support games.",
        },
        "poke": {
            "recommended": "Ignite",
            "pick_rate_recommended": 58,
            "avoid": None,
            "reason": "Poke support converts harass to kills with Ignite closure. Challengers prefer Ignite (~58%) when playing aggressive poke-lane supports.",
        },
        "protect": {
            "recommended": "Exhaust",
            "pick_rate_recommended": 72,
            "avoid": "Ignite",
            "reason": "Protect comp priority is keeping your hypercarry alive. Exhaust is the strongest anti-burst tool — Challengers use it ~72% of protect comp games.",
        },
    },
    "BOTTOM": {
        "assassin_enemy": {
            "recommended": "Barrier",
            "pick_rate_recommended": 55,
            "avoid": "Cleanse",
            "reason": "Barrier absorbs the burst combo window from assassins. Cleanse breaks CC but doesn't reduce the damage that kills you.",
        },
        "engage_enemy": {
            "recommended": "Cleanse",
            "pick_rate_recommended": 60,
            "avoid": "Barrier",
            "reason": "Hard CC chains (Leona, Nautilus, Rell) kill ADCs through Barrier. Cleanse breaks the lockdown and lets you walk out.",
        },
    },
}


def _has_spell(spell_names: list[str], target: str) -> bool:
    return any(target.lower() in s.lower() for s in spell_names)


def _get_keystone_tier(keystone_name: str, position: str, ally_comp_type: str) -> tuple[str, str, str]:
    """
    Returns (tier, icon, note) where tier is 'optimal' | 'situational' | 'unusual'.
    """
    pos_data = _KEYSTONE_DATA.get(keystone_name, {}).get(position)
    if pos_data is None:
        return (
            "unusual",
            "UNUSUAL",
            f"Challengers rarely use this keystone for {position}. "
            f"Verify it matches your champion's kit and intended playstyle.",
        )

    pick_rate   = pos_data["pick_rate"]
    best_comps  = pos_data["best_comps"]
    works_when  = pos_data["works_when"]
    skip_when   = pos_data["skip_when"]

    comp_fits = ally_comp_type in best_comps

    if pick_rate >= 20 and comp_fits:
        tier = "optimal"
        icon = "OPTIMAL"
        note = (
            f"Challenger pick rate: ~{pick_rate}% for {position} — strong choice for this comp. "
            f"Works best when: {works_when}."
        )
    elif comp_fits:
        tier = "situational"
        icon = "SITUATIONAL"
        note = (
            f"Challengers use this in ~{pick_rate}% of {position} games — situational but valid here. "
            f"Works best when: {works_when}."
        )
    else:
        tier = "situational"
        icon = "SITUATIONAL"
        note = (
            f"Challenger {position} pick rate: ~{pick_rate}% (most common in {', '.join(best_comps)} comps). "
            f"Your ally comp is {ally_comp_type} — consider whether your playstyle fits. "
            f"This works when: {works_when}. "
            f"Consider swapping if: {skip_when}."
        )

    return tier, icon, note


def evaluate_runes(
    champion: str,
    position: str,
    keystone_id: int,
    spell1_id: int,
    spell2_id: int,
    ally_comp_type: str,
    enemy_comp_type: str,
    chall_data: list[dict] | None = None,
) -> dict:
    """
    Evaluate rune and summoner spell choices with coaching tone.

    Returns a dict with:
        keystone_name, keystone_tier, keystone_icon, keystone_note,
        spell1_name, spell2_name, spell_tier, spell_icon, spell_note
    """
    keystone_name = get_rune_name(keystone_id)
    spell1_name   = get_spell_name(spell1_id)
    spell2_name   = get_spell_name(spell2_id)
    spell_names   = [spell1_name, spell2_name]

    # ── Keystone evaluation ───────────────────────────────────────────────────
    keystone_tier, keystone_icon, keystone_note = _get_keystone_tier(
        keystone_name, position, ally_comp_type
    )

    # ── Summoner spell evaluation ─────────────────────────────────────────────
    spell_tier = "optimal"
    spell_icon = "OPTIMAL"
    spell_note = "Standard spell choices — no major red flags for this comp."

    pos_spell = _SPELL_COACHING.get(position, {})

    # Determine which scenario applies
    scenario_key = None
    if position == "UTILITY":
        if ally_comp_type in pos_spell:
            scenario_key = ally_comp_type
    elif position == "BOTTOM":
        if enemy_comp_type == "assassin":
            scenario_key = "assassin_enemy"
        elif enemy_comp_type == "engage":
            scenario_key = "engage_enemy"

    if scenario_key and scenario_key in pos_spell:
        rule = pos_spell[scenario_key]
        rec   = rule.get("recommended", "")
        avoid = rule.get("avoid", "")
        pr    = rule.get("pick_rate_recommended", 0)
        reason = rule.get("reason", "")

        has_rec   = rec   and _has_spell(spell_names, rec)
        has_avoid = avoid and _has_spell(spell_names, avoid)

        if has_avoid and not has_rec:
            spell_tier = "situational"
            spell_icon = "SITUATIONAL"
            spell_note = (
                f"Challengers prefer {rec} (~{pr}%) in this comp. {reason}"
            )
        elif not has_rec and rec:
            spell_tier = "situational"
            spell_icon = "SITUATIONAL"
            spell_note = (
                f"Consider {rec} here — Challengers use it in ~{pr}% of {ally_comp_type} comp games. {reason}"
            )

    return {
        "keystone_name":  keystone_name,
        "keystone_tier":  keystone_tier,
        "keystone_icon":  keystone_icon,
        "keystone_note":  keystone_note,
        "spell1_name":    spell1_name,
        "spell2_name":    spell2_name,
        "spell_tier":     spell_tier,
        "spell_icon":     spell_icon,
        "spell_note":     spell_note,
    }
