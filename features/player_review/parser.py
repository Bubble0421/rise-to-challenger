"""Parsing helpers for Player Review match payloads."""
from __future__ import annotations


def infer_role_in_comp(champion_name: str, position: str) -> str:
    carry_pool = {"Jinx", "Caitlyn", "Ezreal", "Aphelios", "Sivir", "Tristana", "KaiSa", "Yunara", "Ashe"}
    assassin_pool = {"Akali", "Zed", "Qiyana", "Talon", "KhaZix", "LeBlanc", "Pyke", "Katarina"}
    support_pool = {"Lulu", "Nami", "Milio", "Janna", "Soraka", "Yuumi", "Sona", "Renata", "Karma"}
    tank_pool = {"Ornn", "Sion", "Sejuani", "Maokai", "Nautilus", "Leona", "Alistar", "Rell", "Poppy"}
    poke_pool = {"Jayce", "Ziggs", "Varus", "Xerath", "Karma", "Ezreal", "Corki"}
    if champion_name in assassin_pool:
        return "assassin"
    if champion_name in support_pool or position == "UTILITY":
        return "support"
    if champion_name in tank_pool or position in {"TOP", "JUNGLE"}:
        return "tank"
    if champion_name in poke_pool:
        return "poke"
    if champion_name in carry_pool or position in {"MIDDLE", "BOTTOM"}:
        return "carry"
    return "carry"


def parse_match(puuid: str, match: dict):
    participants = match["info"]["participants"]
    me = next((p for p in participants if p["puuid"] == puuid), None)
    if not me:
        return None
    team = [p for p in participants if p["teamId"] == me["teamId"]]
    enemy = [p for p in participants if p["teamId"] != me["teamId"]]
    kills, deaths, assists = me["kills"], me["deaths"], me["assists"]
    kda = round((kills + assists) / max(deaths, 1), 2)
    team_kills = sum(p["kills"] for p in team)
    team_damage = sum(p["totalDamageDealtToChampions"] for p in team)
    cs = me["totalMinionsKilled"] + me.get("neutralMinionsKilled", 0)
    duration = match["info"]["gameDuration"] / 60
    my_pos = me.get("teamPosition", "UNKNOWN")
    enemy_laner = next((p["championName"] for p in enemy if p.get("teamPosition") == my_pos), None)

    try:
        keystone_id = me["perks"]["styles"][0]["selections"][0]["perk"]
    except (KeyError, IndexError, TypeError):
        keystone_id = 0
    spell1_id = me.get("summoner1Id", 0)
    spell2_id = me.get("summoner2Id", 0)

    return {
        "match_id": match["metadata"]["matchId"],
        "champion": me["championName"],
        "position": my_pos,
        "win": me["win"],
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "kda": kda,
        "kp": round((kills + assists) / max(team_kills, 1) * 100, 1),
        "cs": cs,
        "cs_per_min": round(cs / max(duration, 1), 1),
        "damage": me["totalDamageDealtToChampions"],
        "vision": me["visionScore"],
        "duration": round(duration, 1),
        "damage_share": round(me["totalDamageDealtToChampions"] / max(team_damage, 1) * 100, 1),
        "participants": participants,
        "items": [me.get(f"item{i}", 0) for i in range(6) if me.get(f"item{i}", 0) != 0],
        "enemy_laner": enemy_laner,
        "ally_champions": [p["championName"] for p in team if p["puuid"] != puuid],
        "enemy_champions": [p["championName"] for p in enemy],
        "role_in_comp": infer_role_in_comp(me["championName"], my_pos),
        "puuid": puuid,
        "match_obj": match,
        "wards_placed": me.get("wardsPlaced", 0),
        "wards_killed": me.get("wardsKilled", 0),
        "vision_wards": me.get("visionWardsBoughtInGame", 0),
        "keystone_id": keystone_id,
        "spell1_id": spell1_id,
        "spell2_id": spell2_id,
    }
