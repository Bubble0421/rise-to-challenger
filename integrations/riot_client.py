"""Riot API client helpers and Riot match parsing utilities."""
from __future__ import annotations

import random
from functools import lru_cache

import pandas as pd
import requests
import streamlit as st
from riotwatcher import ApiError, LolWatcher

from core.config import QUEUE_RANKED_SOLO, QUEUE_TYPE, REGION, REGIONAL, RIOT_API_KEY
from integrations.ddragon_client import champion_icon_url, item_icon_url


watcher = None


@lru_cache(maxsize=1)
def get_watcher():
    if not RIOT_API_KEY:
        raise ValueError("RIOT_API_KEY is not set. Live Riot API features are unavailable.")
    return LolWatcher(RIOT_API_KEY)


@st.cache_data(ttl=300)
def get_summoner(game_name: str, tag_line: str):
    try:
        url = f"https://{REGIONAL}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
        resp = requests.get(url, headers={"X-Riot-Token": RIOT_API_KEY})
        resp.raise_for_status()
        account = resp.json()
        summoner = get_watcher().summoner.by_puuid(REGION, account["puuid"])
        summoner["puuid"] = account["puuid"]
        summoner["gameName"] = game_name
        summoner["tagLine"] = tag_line
        return summoner
    except Exception as e:
        st.error(f"Player not found: {e}")
        return None


@st.cache_data(ttl=300)
def get_league_info(puuid: str):
    try:
        url = f"https://{REGION}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
        resp = requests.get(url, headers={"X-Riot-Token": RIOT_API_KEY})
        resp.raise_for_status()
        entries = resp.json()
        return next((e for e in entries if e["queueType"] == QUEUE_TYPE), None)
    except Exception as e:
        st.error(f"League info error: {e}")
        return None


@st.cache_data(ttl=300)
def get_match_ids(puuid: str, count: int = 10):
    try:
        return get_watcher().match.matchlist_by_puuid(
            REGIONAL, puuid, count=count, queue=QUEUE_RANKED_SOLO
        )
    except ApiError as e:
        st.error(f"Match history error: {e}")
        return []
    except Exception as e:
        st.error(f"Match history unavailable: {e}")
        return []


@st.cache_data(ttl=300)
def get_match_detail(match_id: str):
    try:
        return get_watcher().match.by_id(REGIONAL, match_id)
    except ApiError as e:
        st.error(f"Match detail error: {e}")
        return None
    except Exception as e:
        st.error(f"Match detail unavailable: {e}")
        return None


def parse_player_match(puuid: str, match: dict) -> dict:
    if not match:
        return {}
    participants = match["info"]["participants"]
    player = next((p for p in participants if p["puuid"] == puuid), None)
    if not player:
        return {}

    kills = player["kills"]
    deaths = player["deaths"]
    assists = player["assists"]
    kda = (kills + assists) / max(deaths, 1)
    team_kills = sum(
        p["kills"] for p in participants
        if p["teamId"] == player["teamId"]
    )
    kp = round((kills + assists) / max(team_kills, 1) * 100, 1)

    items = [player.get(f"item{i}", 0) for i in range(7) if player.get(f"item{i}", 0) != 0]

    return {
        "match_id": match["metadata"]["matchId"],
        "champion": player["championName"],
        "champion_icon": champion_icon_url(player["championName"]),
        "position": player.get("teamPosition", "UNKNOWN"),
        "win": player["win"],
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "kda": round(kda, 2),
        "kp": kp,
        "cs": player["totalMinionsKilled"] + player.get("neutralMinionsKilled", 0),
        "damage": player["totalDamageDealtToChampions"],
        "vision": player["visionScore"],
        "duration": round(match["info"]["gameDuration"] / 60, 1),
        "items": items,
        "item_icons": [item_icon_url(i) for i in items],
        "participants": participants,
    }


def parse_all_matches(puuid: str, matches: list) -> pd.DataFrame:
    records = [parse_player_match(puuid, m) for m in matches if m]
    return pd.DataFrame([r for r in records if r])


def analyze_deaths(puuid: str, timeline: dict) -> dict:
    participants = timeline.get("info", {}).get("participants", [])
    player_id = next(
        (p["participantId"] for p in participants if p.get("puuid") == puuid),
        None,
    )
    if player_id is None:
        return {"all_deaths": [], "first_death_minute": None,
                "early_deaths": 0, "mid_deaths": 0, "late_deaths": 0}

    deaths = []
    for frame in timeline.get("info", {}).get("frames", []):
        for event in frame.get("events", []):
            if event["type"] == "CHAMPION_KILL" and event.get("victimId") == player_id:
                minute = event["timestamp"] // 60_000
                deaths.append({
                    "minute": minute,
                    "killer_id": event.get("killerId"),
                    "phase": (
                        "laning" if minute < 15 else
                        "mid_game" if minute < 25 else
                        "late_game"
                    ),
                })

    return {
        "all_deaths": deaths,
        "first_death_minute": deaths[0]["minute"] if deaths else None,
        "early_deaths": sum(1 for d in deaths if d["phase"] == "laning"),
        "mid_deaths": sum(1 for d in deaths if d["phase"] == "mid_game"),
        "late_deaths": sum(1 for d in deaths if d["phase"] == "late_game"),
    }


def get_challenger_avg(champion: str, position: str, matches: list) -> dict:
    records = []
    for match in matches:
        for p in match["info"]["participants"]:
            if p["championName"] == champion and p.get("teamPosition") == position:
                duration = match["info"]["gameDuration"] / 60
                records.append({
                    "kda": (p["kills"] + p["assists"]) / max(p["deaths"], 1),
                    "damage": p["totalDamageDealtToChampions"],
                    "cs_per_min": (p["totalMinionsKilled"] + p.get("neutralMinionsKilled", 0)) / max(duration, 1),
                    "vision": p["visionScore"],
                })
    if not records:
        return {"kda": 0, "damage": 0, "cs_per_min": 0, "vision": 0}
    n = len(records)
    return {
        "kda": round(sum(r["kda"] for r in records) / n, 2),
        "damage": round(sum(r["damage"] for r in records) / n),
        "cs_per_min": round(sum(r["cs_per_min"] for r in records) / n, 1),
        "vision": round(sum(r["vision"] for r in records) / n, 1),
    }


def get_challenger_list():
    try:
        data = get_watcher().league.challenger_by_queue(REGION, QUEUE_TYPE)
        return data.get("entries", [])
    except ApiError as e:
        print(f"Challenger list error: {e}")
        return []
    except Exception as e:
        print(f"Challenger list unavailable: {e}")
        return []


def get_grandmaster_list():
    try:
        data = get_watcher().league.grandmaster_by_queue(REGION, QUEUE_TYPE)
        return data.get("entries", [])
    except ApiError as e:
        print(f"Grandmaster list error: {e}")
        return []
    except Exception as e:
        print(f"Grandmaster list unavailable: {e}")
        return []


def get_master_list():
    try:
        data = get_watcher().league.masters_by_queue(REGION, QUEUE_TYPE)
        return data.get("entries", [])
    except ApiError as e:
        print(f"Master list error: {e}")
        return []
    except Exception as e:
        print(f"Master list unavailable: {e}")
        return []


def get_league_entries_page(tier: str, division: str, page: int = 1):
    try:
        url = (
            f"https://{REGION}.api.riotgames.com/lol/league/v4/entries/"
            f"{QUEUE_TYPE}/{tier}/{division}?page={page}"
        )
        resp = requests.get(url, headers={"X-Riot-Token": RIOT_API_KEY}, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"{tier} {division} page {page} error: {e}")
        return []


def get_sampled_tier_entries(
    tier: str,
    sample_size: int,
    divisions: tuple[str, ...] = ("I", "II", "III", "IV"),
    max_pages_per_division: int = 10,
    random_seed: int = 42,
):
    rng = random.Random(random_seed)
    per_division_target = max(sample_size // max(len(divisions), 1), 1)
    sampled_players = []

    for division in divisions:
        division_entries = []
        for page in range(1, max_pages_per_division + 1):
            page_entries = get_league_entries_page(tier, division, page=page)
            if not page_entries:
                break
            division_entries.extend(page_entries)

        if not division_entries:
            continue

        if len(division_entries) <= per_division_target:
            sampled_players.extend(division_entries)
        else:
            sampled_players.extend(rng.sample(division_entries, per_division_target))

    if len(sampled_players) < sample_size:
        seen = {entry.get("summonerId") for entry in sampled_players}
        overflow_pool = []
        for division in divisions:
            for page in range(1, max_pages_per_division + 1):
                page_entries = get_league_entries_page(tier, division, page=page)
                if not page_entries:
                    break
                for entry in page_entries:
                    summoner_id = entry.get("summonerId")
                    if summoner_id and summoner_id not in seen:
                        overflow_pool.append(entry)
                        seen.add(summoner_id)

        needed = sample_size - len(sampled_players)
        if overflow_pool:
            sampled_players.extend(
                overflow_pool if len(overflow_pool) <= needed else rng.sample(overflow_pool, needed)
            )

    return sampled_players[:sample_size]


def get_diamond_sample(sample_size: int = 240):
    return get_sampled_tier_entries("DIAMOND", sample_size=sample_size)


def get_emerald_sample(sample_size: int = 240):
    return get_sampled_tier_entries("EMERALD", sample_size=sample_size)


def get_platinum_sample(sample_size: int = 200):
    return get_sampled_tier_entries("PLATINUM", sample_size=sample_size)


def get_gold_sample(sample_size: int = 160):
    return get_sampled_tier_entries("GOLD", sample_size=sample_size)


@st.cache_data(ttl=300)
def get_timeline(match_id: str) -> dict | None:
    try:
        return get_watcher().match.timeline_by_match(REGIONAL, match_id)
    except ApiError as e:
        st.warning(f"Timeline unavailable for {match_id}: {e}")
        return None
    except Exception as e:
        st.warning(f"Timeline unavailable for {match_id}: {e}")
        return None


def get_participant_id_from_match(match_detail: dict, puuid: str) -> int | None:
    for p in match_detail["info"]["participants"]:
        if p["puuid"] == puuid:
            return p.get("participantId")
    return None


def get_enemy_participant_id_from_match(match_detail: dict, puuid: str) -> int | None:
    participants = match_detail["info"]["participants"]
    me = next((p for p in participants if p["puuid"] == puuid), None)
    if not me:
        return None
    my_pos = me.get("teamPosition")
    if not my_pos or my_pos == "UNKNOWN":
        return None
    enemy = next(
        (
            p
            for p in participants
            if p["teamId"] != me["teamId"] and p.get("teamPosition") == my_pos
        ),
        None,
    )
    return enemy.get("participantId") if enemy else None
