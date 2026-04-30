"""Timeline API parsing — CS, gold, deaths, item timings, and objectives."""
from __future__ import annotations
import requests

from core.config import CHALL_AVG_ITEM_MIN, PATCH

_big_item_ids: set[int] = set()

OBJECTIVE_MONSTER_TYPES = {"DRAGON", "RIFTHERALD", "BARON_NASHOR", "HORDE"}


def _load_big_items() -> set[int]:
    """Items with total gold >= 2800 from DDragon (cached in module scope)."""
    global _big_item_ids
    if _big_item_ids:
        return _big_item_ids
    try:
        url = f"https://ddragon.leagueoflegends.com/cdn/{PATCH}/data/en_US/item.json"
        data = requests.get(url, timeout=5).json()["data"]
        _big_item_ids = {
            int(k)
            for k, v in data.items()
            if v.get("gold", {}).get("total", 0) >= 2800
            and v.get("gold", {}).get("purchasable", True)
            and v.get("depth", 1) >= 3
        }
    except Exception:
        pass
    return _big_item_ids


def parse_timeline(
    timeline: dict,
    participant_id: int,
    enemy_participant_id: int | None = None,
) -> dict:
    """
    Parse Riot Match-v5 timeline into game-state metrics.

    Returns
    -------
    dict with keys:
      cs_at_5/10/15, enemy_cs_at_5/10/15,
      gold_diff_by_minute {minute: int},
      first_death_minute float|None,
      first_item_minute float|None,
      minutes list[int]
    """
    frames = timeline.get("info", {}).get("frames", [])
    big_items = _load_big_items()

    cs_by_min: dict[int, int] = {}
    gold_by_min: dict[int, int] = {}
    enemy_cs_by_min: dict[int, int] = {}
    enemy_gold_by_min: dict[int, int] = {}

    first_death_minute: float | None = None
    first_champion_kill_minute: float | None = None
    first_item_minute: float | None = None
    death_minutes: list[float] = []
    death_events: list[dict] = []
    item_purchase_minutes: list[dict] = []
    core_item_minutes: list[dict] = []
    objective_events: list[dict] = []

    p_key = str(participant_id)
    e_key = str(enemy_participant_id) if enemy_participant_id else None

    for frame in frames:
        minute = round(frame.get("timestamp", 0) / 60_000)
        pframes = frame.get("participantFrames", {})

        if p_key in pframes:
            pf = pframes[p_key]
            cs_by_min[minute] = pf.get("minionsKilled", 0) + pf.get("jungleMinionsKilled", 0)
            gold_by_min[minute] = pf.get("totalGold", 0)

        if e_key and e_key in pframes:
            ef = pframes[e_key]
            enemy_cs_by_min[minute] = ef.get("minionsKilled", 0) + ef.get("jungleMinionsKilled", 0)
            enemy_gold_by_min[minute] = ef.get("totalGold", 0)

        for event in frame.get("events", []):
            ts_min = event.get("timestamp", 0) / 60_000

            if event["type"] == "CHAMPION_KILL" and first_champion_kill_minute is None:
                first_champion_kill_minute = round(ts_min, 1)

            if event["type"] == "CHAMPION_KILL" and event.get("victimId") == participant_id:
                death_minute = round(ts_min, 1)
                assists = event.get("assistingParticipantIds", []) or []
                death_events.append({
                    "minute": death_minute,
                    "killer_id": event.get("killerId"),
                    "assist_count": len(assists),
                    "position": event.get("position", {}),
                    "first_blood_candidate": first_champion_kill_minute == death_minute,
                })
                death_minutes.append(death_minute)
                if first_death_minute is None:
                    first_death_minute = death_minute

            if event["type"] == "ITEM_PURCHASED" and event.get("participantId") == participant_id:
                item_id = event.get("itemId", 0)
                item_event = {"minute": round(ts_min, 1), "item_id": item_id}
                item_purchase_minutes.append(item_event)
                if item_id in big_items:
                    core_item_minutes.append(item_event)
                    if first_item_minute is None:
                        first_item_minute = item_event["minute"]

            if event["type"] == "ELITE_MONSTER_KILL" and event.get("monsterType") in OBJECTIVE_MONSTER_TYPES:
                objective_events.append({
                    "minute": round(ts_min, 1),
                    "type": event.get("monsterType", "UNKNOWN"),
                    "sub_type": event.get("monsterSubType", ""),
                    "killer_id": event.get("killerId"),
                })

    minutes = sorted(gold_by_min.keys())

    gold_diff_by_minute: dict[int, int] = {}
    if enemy_participant_id:
        for m in minutes:
            gold_diff_by_minute[m] = gold_by_min.get(m, 0) - enemy_gold_by_min.get(m, 0)

    def _snap(src: dict, minute: int) -> int:
        """Return value at minute, falling back ±1 min to handle frame rounding."""
        return src.get(minute, src.get(minute - 1, src.get(minute + 1, 0)))

    return {
        "cs_at_5": _snap(cs_by_min, 5),
        "cs_at_10": _snap(cs_by_min, 10),
        "cs_at_15": _snap(cs_by_min, 15),
        "enemy_cs_at_5": _snap(enemy_cs_by_min, 5),
        "enemy_cs_at_10": _snap(enemy_cs_by_min, 10),
        "enemy_cs_at_15": _snap(enemy_cs_by_min, 15),
        "cs_by_minute": cs_by_min,
        "enemy_cs_by_minute": enemy_cs_by_min,
        "gold_diff_by_minute": gold_diff_by_minute,
        "first_death_minute": first_death_minute,
        "death_minutes": death_minutes,
        "death_events": death_events,
        "deaths_pre_15": sum(1 for m in death_minutes if m < 15),
        "first_item_minute": first_item_minute,
        "item_purchase_minutes": item_purchase_minutes,
        "core_item_minutes": core_item_minutes,
        "objective_events": objective_events,
        "minutes": minutes,
    }


def format_minute(minute: float | int | None) -> str:
    if minute is None:
        return "unknown"
    total_seconds = int(round(float(minute) * 60))
    mins, secs = divmod(total_seconds, 60)
    return f"{mins}:{secs:02d}"


def _death_hypothesis(death_event: dict) -> str:
    minute = death_event.get("minute")
    assists = death_event.get("assist_count", 0)
    first_blood = death_event.get("first_blood_candidate", False)

    if assists >= 2:
        base = "likely collapse or multi-player catch"
    elif assists == 1:
        base = "possible jungle/support gank or 2v2 all-in"
    else:
        base = "possible solo-kill trade, wave punish, or isolated overstep"

    if isinstance(minute, (int, float)) and minute < 5:
        base = f"very early death: {base}; check level spike, ward timing, and lane wave"
    elif isinstance(minute, (int, float)) and minute < 10:
        base = f"laning death: {base}; check wave state, jungle tracking, and cooldown trade"
    elif isinstance(minute, (int, float)) and minute < 15:
        base = f"pre-objective lane death: {base}; check recall timing and river setup"
    else:
        base = f"map-transition death: {base}; check objective timer, fog entry, and teammate spacing"

    if first_blood:
        base = f"first-blood candidate; {base}"
    return base


def _objective_hypothesis(objective_event: dict, death_minutes: list[float]) -> tuple[str, str]:
    obj_min = objective_event.get("minute")
    obj_type = objective_event.get("type", "Objective").replace("_", " ").title()
    prior_deaths = [m for m in death_minutes if isinstance(obj_min, (int, float)) and m < obj_min]
    recent_death = prior_deaths[-1] if prior_deaths else None

    if recent_death is not None:
        gap = float(obj_min) - recent_death
        if gap <= 3:
            hypothesis = (
                f"{obj_type} soon after your death: possible level/item deficit, forced defensive setup, "
                "or over-recovery fight to regain tempo; verify whether this objective was worth contesting."
            )
        else:
            hypothesis = (
                f"{obj_type} after an earlier death: possible tempo recovery window; verify whether lane state, "
                "recall timing, and vision were restored before contesting."
            )
        evidence = f"Objective at {format_minute(obj_min)}; previous death at {format_minute(recent_death)} ({gap:.1f} min earlier)."
    else:
        hypothesis = (
            f"{obj_type} setup: verify whether your team had first move, river vision, and key cooldowns before contesting."
        )
        evidence = f"Objective at {format_minute(obj_min)}; no earlier player death recorded before this checkpoint."
    return hypothesis, evidence


def build_replay_checkpoints(tl: dict) -> list[dict]:
    """Return deterministic replay checkpoints from real timeline timestamps."""
    checkpoints: list[dict] = []

    death_minutes = tl.get("death_minutes", [])
    if death_minutes:
        first_death_event = (tl.get("death_events") or [{}])[0]
        checkpoints.append({
            "timestamp": format_minute(death_minutes[0]),
            "label": "First Death",
            "hypothesis": _death_hypothesis(first_death_event | {"minute": death_minutes[0]}),
            "evidence": (
                f"{first_death_event.get('assist_count', 0)} assist(s) on the kill; "
                f"{'possible first blood' if first_death_event.get('first_blood_candidate') else 'not confirmed as first blood'}"
            ),
            "questions": [
                "Was the nearby wave pushed before you walked up?",
                "Did you know where the enemy jungler or main threat was?",
                "Were Flash, defensive item, or peel cooldowns available?",
                "Did this death affect the next objective setup?",
            ],
        })

    first_item = tl.get("first_item_minute")
    if first_item and first_item > CHALL_AVG_ITEM_MIN + 2:
        start = max(0, first_item - 1)
        checkpoints.append({
            "timestamp": f"{format_minute(start)}-{format_minute(first_item)}",
            "label": "Delayed Core Item Window",
            "questions": [
                "Did you have enough gold to recall earlier?",
                "Was staying for one more wave worth delaying the item spike?",
                "Was an objective spawning within the next 3 minutes?",
            ],
        })

    objective_events = tl.get("objective_events", [])
    if objective_events:
        first_obj = objective_events[0]
        obj_hypothesis, obj_evidence = _objective_hypothesis(first_obj, death_minutes)
        checkpoints.append({
            "timestamp": format_minute(first_obj.get("minute")),
            "label": first_obj.get("type", "Objective").replace("_", " ").title(),
            "hypothesis": obj_hypothesis,
            "evidence": obj_evidence,
            "questions": [
                "Were you level or component-down because of the previous death?",
                "Was the objective already started before you arrived?",
                "Did your team have river vision, or were you face-checking to recover tempo?",
                "Were you the first death in this fight, or did you enter after the fight was already lost?",
            ],
        })

    return checkpoints[:3]




def classify_first_death(minute: float | None) -> str:
    if minute is None:
        return "No deaths recorded"
    if minute < 5:
        return "Very early (pre-5 — likely level 1 or cheesed)"
    if minute < 10:
        return "Early (laning phase)"
    if minute < 15:
        return "Mid laning phase"
    return "Post-laning phase"
