"""Curated demo data for public deployments and portfolio screenshots."""
from __future__ import annotations

import copy
import os
from functools import lru_cache

from features.player_review.parser import parse_match


DEMO_PLAYER_PUUID = "demo-player-puuid"
DEMO_GAME_NAME = "DemoCoach"
DEMO_TAG_LINE = "NA1"


def public_demo_default() -> bool:
    return os.getenv("PUBLIC_DEMO_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}


def _perk_tree(keystone: int) -> dict:
    return {"styles": [{"selections": [{"perk": keystone}]}]}


def _participant(
    *,
    puuid: str,
    name: str,
    champ: str,
    team_id: int,
    pos: str,
    win: bool,
    kills: int,
    deaths: int,
    assists: int,
    damage: int,
    cs: int,
    vision: int,
    items: list[int],
    neutral_cs: int = 0,
    wards_placed: int = 0,
    wards_killed: int = 0,
    control_wards: int = 0,
    keystone: int = 8214,
    spell1: int = 4,
    spell2: int = 14,
) -> dict:
    data = {
        "puuid": puuid,
        "riotIdGameName": name,
        "summonerName": name,
        "championName": champ,
        "teamId": team_id,
        "teamPosition": pos,
        "win": win,
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "totalDamageDealtToChampions": damage,
        "totalMinionsKilled": cs,
        "neutralMinionsKilled": neutral_cs,
        "visionScore": vision,
        "wardsPlaced": wards_placed,
        "wardsKilled": wards_killed,
        "visionWardsBoughtInGame": control_wards,
        "perks": _perk_tree(keystone),
        "summoner1Id": spell1,
        "summoner2Id": spell2,
    }
    for idx in range(6):
        data[f"item{idx}"] = items[idx] if idx < len(items) else 0
    return data


def _match(match_id: str, duration_minutes: float, participants: list[dict]) -> dict:
    return {
        "metadata": {"matchId": match_id},
        "info": {
            "gameDuration": int(duration_minutes * 60),
            "participants": participants,
        },
    }


def _timeline(
    *,
    cs_10: int,
    enemy_cs_10: int,
    cs_15: int,
    enemy_cs_15: int,
    gold_curve: dict[int, int],
    first_death: float | None,
    death_minutes: list[float],
    death_events: list[dict],
    first_item: float | None,
    core_items: list[dict],
    objectives: list[dict],
) -> dict:
    return {
        "cs_at_5": max(cs_10 - 18, 0),
        "cs_at_10": cs_10,
        "cs_at_15": cs_15,
        "enemy_cs_at_5": max(enemy_cs_10 - 18, 0),
        "enemy_cs_at_10": enemy_cs_10,
        "enemy_cs_at_15": enemy_cs_15,
        "cs_by_minute": {5: max(cs_10 - 18, 0), 10: cs_10, 15: cs_15},
        "enemy_cs_by_minute": {5: max(enemy_cs_10 - 18, 0), 10: enemy_cs_10, 15: enemy_cs_15},
        "gold_diff_by_minute": gold_curve,
        "first_death_minute": first_death,
        "death_minutes": death_minutes,
        "death_events": death_events,
        "deaths_pre_15": sum(1 for minute in death_minutes if minute < 15),
        "first_item_minute": first_item,
        "item_purchase_minutes": core_items,
        "core_item_minutes": core_items,
        "objective_events": objectives,
        "minutes": sorted(gold_curve.keys()),
    }


def _seraphine_review_match() -> tuple[dict, dict]:
    participants = [
        _participant(puuid="ally-jax", name="SideJax", champ="Jax", team_id=100, pos="TOP", win=True, kills=8, deaths=3, assists=6, damage=24150, cs=281, vision=28, items=[6632, 3078, 3153, 6333, 3053, 3047]),
        _participant(puuid="ally-lee", name="PathLee", champ="LeeSin", team_id=100, pos="JUNGLE", win=True, kills=5, deaths=4, assists=12, damage=16200, cs=182, neutral_cs=36, vision=42, items=[6692, 3142, 3071, 3026, 3814, 3111]),
        _participant(puuid="ally-irelia", name="MidIrelia", champ="Irelia", team_id=100, pos="MIDDLE", win=True, kills=9, deaths=5, assists=7, damage=21980, cs=246, vision=21, items=[3153, 3078, 6333, 3047, 3053, 3124]),
        _participant(puuid="ally-ezreal", name="BacklineEz", champ="Ezreal", team_id=100, pos="BOTTOM", win=True, kills=11, deaths=4, assists=8, damage=28640, cs=259, vision=24, items=[3508, 6692, 3042, 3158, 3072, 3006]),
        _participant(puuid=DEMO_PLAYER_PUUID, name=DEMO_GAME_NAME, champ="Seraphine", team_id=100, pos="UTILITY", win=True, kills=1, deaths=3, assists=22, damage=14280, cs=42, vision=97, wards_placed=22, wards_killed=7, control_wards=4, items=[3869, 3190, 3117, 2065, 6617, 3504], keystone=8229, spell2=3),
        _participant(puuid="enemy-malphite", name="RockTop", champ="Malphite", team_id=200, pos="TOP", win=False, kills=3, deaths=7, assists=9, damage=15320, cs=229, vision=18, items=[3068, 3110, 3075, 4401, 3024, 6662]),
        _participant(puuid="enemy-viego", name="ResetViego", champ="Viego", team_id=200, pos="JUNGLE", win=False, kills=7, deaths=6, assists=8, damage=23140, cs=184, neutral_cs=28, vision=29, items=[3153, 6333, 3078, 3026, 3814, 3047]),
        _participant(puuid="enemy-hwei", name="InkMage", champ="Hwei", team_id=200, pos="MIDDLE", win=False, kills=5, deaths=5, assists=10, damage=26780, cs=244, vision=18, items=[6655, 3020, 4637, 3135, 3089, 3157]),
        _participant(puuid="enemy-lucian", name="DashADC", champ="Lucian", team_id=200, pos="BOTTOM", win=False, kills=8, deaths=6, assists=6, damage=25260, cs=251, vision=17, items=[6671, 3006, 3036, 3095, 3072, 3033]),
        _participant(puuid="enemy-panth", name="SpearSupp", champ="Pantheon", team_id=200, pos="UTILITY", win=False, kills=2, deaths=8, assists=13, damage=11980, cs=41, vision=58, wards_placed=18, wards_killed=4, control_wards=3, items=[3865, 6692, 3117, 2055, 1036, 0], keystone=8439, spell2=14),
    ]
    tl = _timeline(
        cs_10=11,
        enemy_cs_10=12,
        cs_15=17,
        enemy_cs_15=19,
        gold_curve={0: 0, 5: 80, 10: 120, 15: 240, 20: 380, 25: 540, 30: 700, 35: 920, 40: 1180},
        first_death=9.4,
        death_minutes=[9.4, 22.1, 31.8],
        death_events=[
            {"minute": 9.4, "killer_id": 10, "assist_count": 1, "position": {}, "first_blood_candidate": False},
            {"minute": 22.1, "killer_id": 7, "assist_count": 2, "position": {}, "first_blood_candidate": False},
            {"minute": 31.8, "killer_id": 9, "assist_count": 2, "position": {}, "first_blood_candidate": False},
        ],
        first_item=12.4,
        core_items=[{"minute": 12.4, "item_id": 3190}, {"minute": 18.7, "item_id": 3117}, {"minute": 28.2, "item_id": 6617}],
        objectives=[
            {"minute": 6.2, "type": "DRAGON", "sub_type": "CHEMTECH", "killer_id": 2},
            {"minute": 20.8, "type": "DRAGON", "sub_type": "MOUNTAIN", "killer_id": 2},
            {"minute": 29.5, "type": "BARON_NASHOR", "sub_type": "", "killer_id": 1},
        ],
    )
    return _match("DEMO-SERA-001", 34.8, participants), tl


def _seraphine_loss_match() -> tuple[dict, dict]:
    participants = [
        _participant(puuid="ally-ornn", name="FrontlineOrnn", champ="Ornn", team_id=100, pos="TOP", win=False, kills=2, deaths=6, assists=7, damage=14800, cs=214, vision=24, items=[6662, 3111, 3068, 3075, 4401, 3024]),
        _participant(puuid="ally-sej", name="RiverSej", champ="Sejuani", team_id=100, pos="JUNGLE", win=False, kills=3, deaths=7, assists=10, damage=12500, cs=169, neutral_cs=32, vision=35, items=[6664, 3111, 3742, 3075, 3065, 3024]),
        _participant(puuid="ally-ahri", name="PickAhri", champ="Ahri", team_id=100, pos="MIDDLE", win=False, kills=5, deaths=5, assists=6, damage=19840, cs=228, vision=19, items=[6655, 3020, 4645, 3089, 3135, 3157]),
        _participant(puuid="ally-jinx", name="ScaleJinx", champ="Jinx", team_id=100, pos="BOTTOM", win=False, kills=6, deaths=6, assists=5, damage=24890, cs=247, vision=15, items=[6672, 3006, 3094, 3031, 3036, 3072]),
        _participant(puuid=DEMO_PLAYER_PUUID, name=DEMO_GAME_NAME, champ="Seraphine", team_id=100, pos="UTILITY", win=False, kills=2, deaths=8, assists=14, damage=13120, cs=39, vision=68, wards_placed=18, wards_killed=3, control_wards=2, items=[3869, 2065, 6617, 3158, 3117, 3190], keystone=8229, spell2=3),
        _participant(puuid="enemy-renek", name="LaneGator", champ="Renekton", team_id=200, pos="TOP", win=True, kills=7, deaths=3, assists=6, damage=22120, cs=232, vision=14, items=[6630, 3071, 3053, 6333, 3047, 3026]),
        _participant(puuid="enemy-viego2", name="SnowballViego", champ="Viego", team_id=200, pos="JUNGLE", win=True, kills=8, deaths=4, assists=9, damage=24330, cs=188, neutral_cs=30, vision=26, items=[3153, 3078, 3026, 6333, 3814, 3047]),
        _participant(puuid="enemy-syndra", name="BurstSyndra", champ="Syndra", team_id=200, pos="MIDDLE", win=True, kills=9, deaths=3, assists=7, damage=29100, cs=238, vision=17, items=[6655, 3020, 4645, 3089, 3135, 3157]),
        _participant(puuid="enemy-cait", name="PressureCait", champ="Caitlyn", team_id=200, pos="BOTTOM", win=True, kills=10, deaths=2, assists=8, damage=27950, cs=272, vision=18, items=[6671, 3006, 3036, 3095, 3072, 3031]),
        _participant(puuid="enemy-thresh", name="HookThresh", champ="Thresh", team_id=200, pos="UTILITY", win=True, kills=1, deaths=4, assists=18, damage=9040, cs=40, vision=74, wards_placed=21, wards_killed=8, control_wards=4, items=[3860, 3190, 3109, 3117, 2055, 0], keystone=8439, spell2=4),
    ]
    tl = _timeline(
        cs_10=10,
        enemy_cs_10=13,
        cs_15=15,
        enemy_cs_15=20,
        gold_curve={0: 0, 5: -120, 10: -260, 15: -420, 20: -760, 25: -1050, 30: -1410},
        first_death=4.6,
        death_minutes=[4.6, 7.2, 13.1, 18.4, 23.2, 27.0, 30.3, 33.1],
        death_events=[
            {"minute": 4.6, "killer_id": 10, "assist_count": 1, "position": {}, "first_blood_candidate": True},
            {"minute": 7.2, "killer_id": 8, "assist_count": 2, "position": {}, "first_blood_candidate": False},
        ],
        first_item=15.8,
        core_items=[{"minute": 15.8, "item_id": 6617}, {"minute": 22.5, "item_id": 3117}],
        objectives=[
            {"minute": 6.1, "type": "DRAGON", "sub_type": "HEXTECH", "killer_id": 7},
            {"minute": 20.2, "type": "RIFTHERALD", "sub_type": "", "killer_id": 6},
            {"minute": 25.0, "type": "DRAGON", "sub_type": "INFERNAL", "killer_id": 7},
        ],
    )
    return _match("DEMO-SERA-002", 33.4, participants), tl


def _jinx_match(match_id: str, *, win: bool, damage: int, cs: int, kills: int, deaths: int, assists: int) -> dict:
    blue_win = win
    demo_team = 100 if blue_win else 200
    enemy_team = 200 if blue_win else 100
    demo_participant = _participant(
        puuid=DEMO_PLAYER_PUUID if match_id == "DEMO-JINX-001" else f"jinx-{match_id}",
        name=DEMO_GAME_NAME if match_id == "DEMO-JINX-001" else f"Jinx{match_id[-1]}",
        champ="Jinx",
        team_id=demo_team,
        pos="BOTTOM",
        win=win,
        kills=kills,
        deaths=deaths,
        assists=assists,
        damage=damage,
        cs=cs,
        vision=18,
        items=[6672, 3006, 3094, 3031, 3036, 3072],
        keystone=8008,
        spell1=7,
        spell2=4,
    )
    enemy_adc = _participant(
        puuid=f"cait-{match_id}",
        name=f"Cait{match_id[-1]}",
        champ="Caitlyn",
        team_id=enemy_team,
        pos="BOTTOM",
        win=not win,
        kills=7 if not win else 4,
        deaths=4 if not win else 6,
        assists=6,
        damage=23300 if not win else 20100,
        cs=241,
        vision=17,
        items=[6671, 3006, 3036, 3095, 3072, 3031],
        keystone=8021,
        spell1=7,
        spell2=4,
    )
    teammates = [
        _participant(puuid=f"top-{match_id}", name="TankTop", champ="Ornn", team_id=demo_team, pos="TOP", win=win, kills=2, deaths=5, assists=11, damage=14100, cs=219, vision=22, items=[6662, 3111, 3068, 3075, 4401, 3024]),
        _participant(puuid=f"jg-{match_id}", name="PathJarvan", champ="Jarvan IV", team_id=demo_team, pos="JUNGLE", win=win, kills=4, deaths=6, assists=13, damage=16800, cs=170, neutral_cs=34, vision=30, items=[6692, 3071, 3814, 3026, 6333, 3047]),
        _participant(puuid=f"mid-{match_id}", name="WaveLux", champ="Lux", team_id=demo_team, pos="MIDDLE", win=win, kills=6, deaths=5, assists=9, damage=24100, cs=218, vision=20, items=[6655, 3020, 4628, 3089, 3135, 3157]),
        _participant(puuid=f"sup-{match_id}", name="PeelLulu", champ="Lulu", team_id=demo_team, pos="UTILITY", win=win, kills=1, deaths=5, assists=18, damage=8220, cs=36, vision=72, wards_placed=20, wards_killed=6, control_wards=4, items=[3869, 3504, 3117, 6616, 2065, 0], keystone=8214, spell2=3),
    ]
    enemies = [
        _participant(puuid=f"etop-{match_id}", name="BruiserAatrox", champ="Aatrox", team_id=enemy_team, pos="TOP", win=not win, kills=5, deaths=4, assists=7, damage=19800, cs=225, vision=16, items=[6630, 3071, 3053, 6333, 3047, 3026]),
        _participant(puuid=f"ejg-{match_id}", name="ResetViego", champ="Viego", team_id=enemy_team, pos="JUNGLE", win=not win, kills=6, deaths=4, assists=8, damage=20900, cs=181, neutral_cs=27, vision=24, items=[3153, 3078, 6333, 3026, 3814, 3047]),
        _participant(puuid=f"emid-{match_id}", name="PressureOri", champ="Orianna", team_id=enemy_team, pos="MIDDLE", win=not win, kills=4, deaths=5, assists=10, damage=21400, cs=229, vision=18, items=[6655, 3020, 4628, 3089, 3135, 3157]),
        enemy_adc,
        _participant(puuid=f"esup-{match_id}", name="HookNaut", champ="Nautilus", team_id=enemy_team, pos="UTILITY", win=not win, kills=2, deaths=7, assists=15, damage=8960, cs=33, vision=66, wards_placed=18, wards_killed=4, control_wards=3, items=[3860, 3190, 3109, 3117, 2055, 0], keystone=8439, spell2=4),
    ]
    participants = teammates + [demo_participant] + enemies if demo_team == 100 else enemies + teammates + [demo_participant]
    return _match(match_id, 32.1, participants)


def _lux_match() -> dict:
    participants = [
        _participant(puuid="ltop", name="StoneTop", champ="Malphite", team_id=100, pos="TOP", win=True, kills=3, deaths=4, assists=10, damage=13200, cs=208, vision=20, items=[3068, 3111, 3075, 4401, 3024, 6662]),
        _participant(puuid="ljg", name="TempoVi", champ="Vi", team_id=100, pos="JUNGLE", win=True, kills=7, deaths=5, assists=9, damage=19900, cs=178, neutral_cs=31, vision=28, items=[6692, 3071, 6333, 3026, 3814, 3047]),
        _participant(puuid=DEMO_PLAYER_PUUID, name=DEMO_GAME_NAME, champ="Lux", team_id=100, pos="MIDDLE", win=True, kills=10, deaths=2, assists=9, damage=31240, cs=238, vision=19, items=[6655, 3020, 4628, 3089, 3135, 3157], keystone=8229, spell2=4),
        _participant(puuid="ladc", name="PokeEzreal", champ="Ezreal", team_id=100, pos="BOTTOM", win=True, kills=8, deaths=4, assists=7, damage=25110, cs=241, vision=17, items=[3508, 6692, 3042, 3072, 3158, 3006]),
        _participant(puuid="lsup", name="ShieldMilio", champ="Milio", team_id=100, pos="UTILITY", win=True, kills=1, deaths=3, assists=16, damage=7040, cs=30, vision=75, wards_placed=19, wards_killed=5, control_wards=4, items=[3869, 3504, 3117, 6616, 2065, 0], keystone=8214, spell2=3),
        _participant(puuid="etop2", name="BladeCam", champ="Camille", team_id=200, pos="TOP", win=False, kills=4, deaths=6, assists=5, damage=18240, cs=221, vision=15, items=[6632, 3078, 3153, 6333, 3047, 3053]),
        _participant(puuid="ejg2", name="BurstEve", champ="Evelynn", team_id=200, pos="JUNGLE", win=False, kills=6, deaths=7, assists=4, damage=20850, cs=171, neutral_cs=24, vision=18, items=[4633, 3020, 3100, 3089, 3135, 3157]),
        _participant(puuid="emid2", name="DashYone", champ="Yone", team_id=200, pos="MIDDLE", win=False, kills=5, deaths=7, assists=3, damage=22420, cs=236, vision=16, items=[6673, 3006, 3031, 3094, 3072, 3036]),
        _participant(puuid="eadc2", name="LaneAshe", champ="Ashe", team_id=200, pos="BOTTOM", win=False, kills=2, deaths=6, assists=8, damage=16720, cs=228, vision=15, items=[6672, 3006, 3094, 3031, 3072, 3036]),
        _participant(puuid="esup2", name="RoamPyke", champ="Pyke", team_id=200, pos="UTILITY", win=False, kills=3, deaths=8, assists=7, damage=9480, cs=28, vision=49, wards_placed=15, wards_killed=6, control_wards=2, items=[3860, 3142, 6692, 3117, 2055, 0], keystone=9923, spell2=4),
    ]
    return _match("DEMO-LUX-001", 30.6, participants)


def _vladimir_match() -> tuple[dict, dict]:
    participants = [
        _participant(puuid="vtop", name="SideTrynd", champ="Tryndamere", team_id=100, pos="TOP", win=False, kills=4, deaths=7, assists=3, damage=20400, cs=251, vision=12, items=[6673, 3006, 3031, 3094, 3072, 3036]),
        _participant(puuid="vjg", name="FearFiddle", champ="Fiddlesticks", team_id=100, pos="JUNGLE", win=False, kills=3, deaths=8, assists=10, damage=18220, cs=161, neutral_cs=36, vision=31, items=[4645, 3020, 3165, 3135, 3157, 3020]),
        _participant(puuid=DEMO_PLAYER_PUUID, name=DEMO_GAME_NAME, champ="Vladimir", team_id=100, pos="MIDDLE", win=False, kills=4, deaths=8, assists=4, damage=22147, cs=246, vision=17, items=[3152, 3020, 4637, 3135, 3089, 3157], keystone=8214, spell2=4),
        _participant(puuid="vadc", name="ScaleSmolder", champ="Smolder", team_id=100, pos="BOTTOM", win=False, kills=5, deaths=6, assists=7, damage=18890, cs=244, vision=14, items=[6672, 3006, 3031, 3036, 3072, 3094]),
        _participant(puuid="vsup", name="PeelJanna", champ="Janna", team_id=100, pos="UTILITY", win=False, kills=0, deaths=5, assists=12, damage=5320, cs=24, vision=63, wards_placed=17, wards_killed=4, control_wards=3, items=[3869, 3504, 3117, 6616, 2065, 0], keystone=8214, spell2=3),
        _participant(puuid="etopv", name="DiveRenek", champ="Renekton", team_id=200, pos="TOP", win=True, kills=6, deaths=4, assists=8, damage=21320, cs=236, vision=13, items=[6630, 3071, 3053, 6333, 3047, 3026]),
        _participant(puuid="ejgv", name="TempoVi2", champ="Vi", team_id=200, pos="JUNGLE", win=True, kills=8, deaths=4, assists=9, damage=19400, cs=176, neutral_cs=29, vision=23, items=[6692, 3071, 6333, 3026, 3814, 3047]),
        _participant(puuid="emidv", name="BurstAkali", champ="Akali", team_id=200, pos="MIDDLE", win=True, kills=11, deaths=3, assists=6, damage=28220, cs=239, vision=15, items=[3152, 3020, 3100, 3135, 3089, 3157]),
        _participant(puuid="eadcv", name="DashLucian", champ="Lucian", team_id=200, pos="BOTTOM", win=True, kills=7, deaths=4, assists=10, damage=24600, cs=238, vision=16, items=[6671, 3006, 3036, 3072, 3095, 3031]),
        _participant(puuid="esupv", name="HookThresh", champ="Thresh", team_id=200, pos="UTILITY", win=True, kills=1, deaths=4, assists=19, damage=8120, cs=27, vision=69, wards_placed=19, wards_killed=7, control_wards=4, items=[3860, 3190, 3109, 3117, 2055, 0], keystone=8439, spell2=4),
    ]
    tl = _timeline(
        cs_10=75,
        enemy_cs_10=59,
        cs_15=112,
        enemy_cs_15=87,
        gold_curve={0: 0, 5: 60, 10: 180, 15: 120, 20: -140, 25: -420, 30: -860, 35: -1230},
        first_death=3.6,
        death_minutes=[3.6, 6.4, 12.3, 16.8, 21.5, 24.8, 29.9, 33.2],
        death_events=[
            {"minute": 3.6, "killer_id": 8, "assist_count": 0, "position": {}, "first_blood_candidate": True},
            {"minute": 6.4, "killer_id": 7, "assist_count": 1, "position": {}, "first_blood_candidate": False},
        ],
        first_item=14.8,
        core_items=[{"minute": 14.8, "item_id": 3152}, {"minute": 21.0, "item_id": 4637}],
        objectives=[
            {"minute": 6.4, "type": "DRAGON", "sub_type": "MOUNTAIN", "killer_id": 7},
            {"minute": 15.2, "type": "RIFTHERALD", "sub_type": "", "killer_id": 6},
            {"minute": 23.9, "type": "DRAGON", "sub_type": "OCEAN", "killer_id": 7},
        ],
    )
    return _match("DEMO-VLAD-001", 34.2, participants), tl


@lru_cache(maxsize=1)
def get_demo_matches() -> list[dict]:
    sera_win, _ = _seraphine_review_match()
    sera_loss, _ = _seraphine_loss_match()
    lux_win = _lux_match()
    vlad_loss, _ = _vladimir_match()
    jinx_matches = [
        _jinx_match("DEMO-JINX-001", win=True, damage=24100, cs=252, kills=9, deaths=3, assists=7),
        _jinx_match("DEMO-JINX-002", win=False, damage=21950, cs=237, kills=6, deaths=5, assists=5),
        _jinx_match("DEMO-JINX-003", win=True, damage=25820, cs=265, kills=10, deaths=4, assists=6),
        _jinx_match("DEMO-JINX-004", win=True, damage=23380, cs=247, kills=8, deaths=3, assists=9),
        _jinx_match("DEMO-JINX-005", win=False, damage=20720, cs=231, kills=5, deaths=6, assists=4),
        _jinx_match("DEMO-JINX-006", win=True, damage=24940, cs=259, kills=11, deaths=2, assists=8),
    ]
    return [sera_win, sera_loss, lux_win, vlad_loss, *jinx_matches]


@lru_cache(maxsize=1)
def get_demo_timelines() -> dict[str, dict]:
    sera_win, sera_win_tl = _seraphine_review_match()
    sera_loss, sera_loss_tl = _seraphine_loss_match()
    vlad_loss, vlad_loss_tl = _vladimir_match()
    jinx_tl = _timeline(
        cs_10=83,
        enemy_cs_10=88,
        cs_15=127,
        enemy_cs_15=131,
        gold_curve={0: 0, 5: -40, 10: -120, 15: 20, 20: 210, 25: 480, 30: 710},
        first_death=8.1,
        death_minutes=[8.1, 19.6, 27.2],
        death_events=[{"minute": 8.1, "killer_id": 10, "assist_count": 1, "position": {}, "first_blood_candidate": False}],
        first_item=12.9,
        core_items=[{"minute": 12.9, "item_id": 6672}, {"minute": 18.2, "item_id": 3094}],
        objectives=[{"minute": 6.0, "type": "DRAGON", "sub_type": "CLOUD", "killer_id": 2}, {"minute": 21.1, "type": "DRAGON", "sub_type": "HEXTECH", "killer_id": 2}],
    )
    return {
        sera_win["metadata"]["matchId"]: sera_win_tl,
        sera_loss["metadata"]["matchId"]: sera_loss_tl,
        vlad_loss["metadata"]["matchId"]: vlad_loss_tl,
        "DEMO-JINX-001": jinx_tl,
    }


@lru_cache(maxsize=1)
def get_demo_player_review_bundle() -> dict:
    matches = get_demo_matches()
    timelines = get_demo_timelines()
    demo_matches = [match for match in matches if any(p["puuid"] == DEMO_PLAYER_PUUID for p in match["info"]["participants"])]
    parsed = []
    for match in demo_matches:
        parsed_match = parse_match(DEMO_PLAYER_PUUID, copy.deepcopy(match))
        if parsed_match:
            parsed.append(parsed_match)
    return {
        "summoner": {
            "puuid": DEMO_PLAYER_PUUID,
            "profileIconId": 588,
            "summonerLevel": 412,
            "gameName": DEMO_GAME_NAME,
            "tagLine": DEMO_TAG_LINE,
        },
        "league": {
            "tier": "MASTER",
            "rank": "I",
            "leaguePoints": 187,
            "wins": 118,
            "losses": 92,
        },
        "parsed_matches": parsed,
        "benchmark_matches": matches,
        "rank_matches": matches,
        "timelines": timelines,
    }
