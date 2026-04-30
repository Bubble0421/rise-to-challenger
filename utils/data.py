import json
from functools import lru_cache
from pathlib import Path


DATA_DIR = Path("data")
LEGACY_META_CACHE = DATA_DIR / "meta_cache.json"
# Ordered from highest to lowest (index = rank level)
RANK_TIER_ORDER = ["Challenger", "Grandmaster", "Master", "Diamond", "Emerald", "Platinum", "Gold"]

RANK_FILE_MAP = {
    "Challenger":  DATA_DIR / "challenger_matches.json",
    "Grandmaster": DATA_DIR / "grandmaster_matches.json",
    "Master":      DATA_DIR / "master_matches.json",
    "Diamond":     DATA_DIR / "diamond_matches.json",
    "Emerald":     DATA_DIR / "emerald_matches.json",
    "Platinum":    DATA_DIR / "platinum_matches.json",
    "Gold":        DATA_DIR / "gold_matches.json",
}

def _available_ranks() -> list:
    """Return only ranks that have a data file on disk (or legacy fallback)."""
    available = []
    for rank in RANK_TIER_ORDER:
        path = RANK_FILE_MAP[rank]
        if path.exists():
            available.append(rank)
        elif rank == "Challenger" and LEGACY_META_CACHE.exists():
            available.append(rank)
    return available

RANK_OPTIONS = [f"{r}+" for r in _available_ranks()]
PERMANENT_DATA_NOTE = "Based on Master+ NA matches · All available high-elo data included"


@lru_cache(maxsize=8)
def _load_json_file_cached(path_str: str) -> list:
    path = Path(path_str)
    if not path.exists():
        return []

    with path.open() as f:
        return json.load(f)


def load_json_file(path: Path) -> list:
    return _load_json_file_cached(str(path))


def save_json_file(path: Path, data: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f)


def load_rank_matches(rank_label: str) -> list:
    """Load all matches at the given rank AND above.
    rank_label should be like 'Challenger+', 'Master+', etc.
    """
    base = rank_label.rstrip("+")
    if base not in RANK_TIER_ORDER:
        # Fallback: load all
        base = RANK_TIER_ORDER[0]

    # Collect all ranks at or above base
    base_idx = RANK_TIER_ORDER.index(base)
    ranks_to_load = RANK_TIER_ORDER[:base_idx + 1]  # highest → base (inclusive)

    merged = []
    seen_ids = set()
    for rank in ranks_to_load:
        path = RANK_FILE_MAP[rank]
        source = load_json_file(path)
        if not source and rank == "Challenger":
            source = load_json_file(LEGACY_META_CACHE)
        for match in source:
            match_id = match.get("metadata", {}).get("matchId")
            if match_id and match_id not in seen_ids:
                merged.append(match)
                seen_ids.add(match_id)
    return merged


def rank_key_to_label(rank_key: str) -> str:
    return rank_key.title()
