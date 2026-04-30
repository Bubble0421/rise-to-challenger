"""Benchmark and reference data helpers for Player Review."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.data import load_rank_matches


RANK_TO_DATASET = {
    "CHALLENGER": "Challenger",
    "GRANDMASTER": "Grandmaster",
    "MASTER": "Master",
    "DIAMOND": "Diamond",
    "EMERALD": "Emerald",
    "PLATINUM": "Platinum",
    "GOLD": "Gold",
}


@st.cache_resource
def load_benchmark_matches(rank_label: str):
    return load_rank_matches(rank_label)


@st.cache_resource
def load_optimal_builds():
    matches = load_rank_matches("Challenger")
    builds = {}
    for match in matches:
        for p in match.get("info", {}).get("participants", []):
            pos = p.get("teamPosition")
            if not pos or pos == "UNKNOWN" or not p["win"]:
                continue
            key = (p["championName"], pos)
            items = tuple(i for i in (p.get(f"item{j}", 0) for j in range(6)) if i != 0)
            if not items:
                continue
            builds.setdefault(key, {})
            builds[key][items] = builds[key].get(items, 0) + 1
    return {key: list(max(item_map, key=item_map.get)) for key, item_map in builds.items()}


def dataset_for_tier(tier: str | None) -> str:
    return RANK_TO_DATASET.get((tier or "").upper(), "All Ranks Combined")


def get_position_benchmark(matches: list, champion: str, position: str) -> tuple[dict, str]:
    rows, champ_rows = [], []
    for match in matches:
        for p in match.get("info", {}).get("participants", []):
            if p.get("teamPosition") != position:
                continue
            team = [pp for pp in match["info"]["participants"] if pp["teamId"] == p["teamId"]]
            team_kills = sum(pp["kills"] for pp in team)
            team_damage = sum(pp["totalDamageDealtToChampions"] for pp in team)
            duration = match["info"]["gameDuration"] / 60
            row = {
                "kda": (p["kills"] + p["assists"]) / max(p["deaths"], 1),
                "damage": p["totalDamageDealtToChampions"],
                "cs_per_min": (p["totalMinionsKilled"] + p.get("neutralMinionsKilled", 0)) / max(duration, 1),
                "vision": p["visionScore"],
                "kp": (p["kills"] + p["assists"]) / max(team_kills, 1) * 100,
                "deaths": p["deaths"],
                "damage_share": p["totalDamageDealtToChampions"] / max(team_damage, 1) * 100,
                "champion": p["championName"],
                "wards_placed": p.get("wardsPlaced", 0),
            }
            rows.append(row)
            if p["championName"] == champion:
                champ_rows.append(row)

    if len(champ_rows) >= 20:
        source = champ_rows
        label = f"{champion} · {position} avg ({len(champ_rows)} games)"
    elif rows:
        source = rows
        label = f"Position avg · {position} ({len(rows)} games, insufficient {champion} data)"
    else:
        return ({"kda": 0, "damage": 0, "cs_per_min": 0, "vision": 0,
                 "kp": 0, "deaths": 0, "damage_share": 0}, "No data")

    avgs = {
        k: round(sum(r[k] for r in source) / len(source), 2 if k in {"kda", "cs_per_min"} else 1)
        for k in ("kda", "damage", "cs_per_min", "vision", "kp", "deaths", "damage_share", "wards_placed")
    }
    return avgs, label


def get_rank_meta_context(matches: list, champion: str, position: str):
    rows = []
    for match in matches:
        for p in match.get("info", {}).get("participants", []):
            pos = p.get("teamPosition")
            if not pos or pos == "UNKNOWN":
                continue
            rows.append({"champion": p["championName"], "position": pos, "win": int(p["win"])})
    if not rows:
        return 0.0, 0.0
    df = pd.DataFrame(rows)
    champ = df.groupby(["champion", "position"]).agg(games=("win", "count"), wins=("win", "sum")).reset_index()
    champ["win_rate"] = champ["wins"] / champ["games"] * 100
    champion_row = champ[(champ["champion"] == champion) & (champ["position"] == position)]
    champ_wr = round(float(champion_row["win_rate"].iloc[0]), 1) if not champion_row.empty else 0.0
    role_rows = champ[champ["position"] == position]
    best_wr = round(float(role_rows["win_rate"].max()), 1) if not role_rows.empty else 0.0
    return champ_wr, best_wr
