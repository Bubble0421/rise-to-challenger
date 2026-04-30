"""Data Dragon helpers for assets and static LoL metadata."""
from __future__ import annotations

import requests
import streamlit as st

from core.config import PATCH


_ddragon_champ_map: dict[str, str] = {}


def _build_champ_map() -> dict[str, str]:
    """Fetch champion metadata and build lowercase name/id to DDragon id."""
    try:
        url = f"https://ddragon.leagueoflegends.com/cdn/{PATCH}/data/en_US/champion.json"
        data = requests.get(url, timeout=6).json()["data"]
        mapping = {}
        for ddragon_id, info in data.items():
            mapping[ddragon_id.lower()] = ddragon_id
            display = info.get("name", "").lower()
            if display:
                mapping[display] = ddragon_id
        return mapping
    except Exception:
        return {}


def ddragon_id(champion_name: str) -> str:
    global _ddragon_champ_map
    if not _ddragon_champ_map:
        _ddragon_champ_map = _build_champ_map()
    return _ddragon_champ_map.get(champion_name.lower(), champion_name)


def champion_icon_url(champion_name: str) -> str:
    name = ddragon_id(champion_name)
    return f"https://ddragon.leagueoflegends.com/cdn/{PATCH}/img/champion/{name}.png"


def item_icon_url(item_id: int) -> str:
    return f"https://ddragon.leagueoflegends.com/cdn/{PATCH}/img/item/{item_id}.png"


def profile_icon_url(icon_id: int) -> str:
    return f"https://ddragon.leagueoflegends.com/cdn/{PATCH}/img/profileicon/{icon_id}.png"


def rank_icon_url(tier: str) -> str:
    return f"https://opgg-static.akamaized.net/images/medals_new/{tier.lower()}.png"


@st.cache_data
def get_item_names() -> dict[int, str]:
    try:
        url = f"https://ddragon.leagueoflegends.com/cdn/{PATCH}/data/en_US/item.json"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        return {int(k): v["name"] for k, v in data["data"].items()}
    except Exception:
        return {}


def get_item_name(item_id: int) -> str:
    return get_item_names().get(item_id, f"Unknown Item {item_id}")
