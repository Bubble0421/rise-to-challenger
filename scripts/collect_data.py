"""
Incremental Challenger/GM/Master match data collector.

Appends new matches to existing JSON files — never overwrites duplicates.
Respects Riot personal dev key rate limits: 100 req / 2 min → 1.3s sleep.

Usage examples:
  python scripts/collect_data.py --tier challenger
  python scripts/collect_data.py --tier grandmaster --max-players 300
  python scripts/collect_data.py --tier master     --max-players 200
  python scripts/collect_data.py --all             --max-players 300
  python scripts/collect_data.py --tier challenger --matches-per-player 30 --dry-run
"""

import argparse
import sys
import time
from pathlib import Path

# ── project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from api import (
    watcher,
    REGIONAL,
    get_challenger_list,
    get_grandmaster_list,
    get_master_list,
)
from utils.data import RANK_FILE_MAP, load_json_file, save_json_file

# ── rate-limit config ─────────────────────────────────────────────────────────
# Personal dev key: 20 req/s, 100 req/2min.
# Binding constraint: 100 / 120s = 0.833 req/s → sleep 1.3s to be safe.
SLEEP = 1.3
SAVE_EVERY = 10      # checkpoint save interval (players)
QUEUE_RANKED = 420   # Solo/Duo ranked queue


# ── helpers ───────────────────────────────────────────────────────────────────

def load_existing_ids(path: Path) -> set[str]:
    return {m["metadata"]["matchId"] for m in load_json_file(path)}


def _matchlist(puuid: str, count: int) -> list[str]:
    try:
        ids = watcher.match.matchlist_by_puuid(
            REGIONAL, puuid, count=count, queue=QUEUE_RANKED
        )
        time.sleep(SLEEP)
        return ids or []
    except Exception as e:
        print(f"      matchlist error: {e}")
        time.sleep(SLEEP)
        return []


def _fetch_match(match_id: str) -> dict | None:
    try:
        m = watcher.match.by_id(REGIONAL, match_id)
        time.sleep(SLEEP)
        return m
    except Exception as e:
        print(f"      match {match_id} error: {e}")
        time.sleep(SLEEP)
        return None


def _eta(elapsed: float, done: int, total: int) -> str:
    if done == 0:
        return "?"
    rate = done / elapsed
    remaining = (total - done) / rate
    m, s = divmod(int(remaining), 60)
    return f"{m}m{s:02d}s"


# ── core collector ────────────────────────────────────────────────────────────

def collect_tier(
    tier: str,
    matches_per_player: int,
    max_players: int | None,
    dry_run: bool,
    seed: int = 42,
) -> int:
    """
    Fetch new ranked matches for `tier` and append them to the JSON file.
    Returns number of new matches added.
    """
    path = RANK_FILE_MAP[tier]
    existing_ids = load_existing_ids(path)
    existing_matches = load_json_file(path)

    print(f"\n{'='*60}")
    print(f"  Tier: {tier}   |   existing: {len(existing_matches)} matches")
    print(f"  matches_per_player={matches_per_player}   max_players={max_players}")
    print(f"  {'[DRY RUN] ' if dry_run else ''}Output: {path}")
    print(f"{'='*60}")

    # ── get leaderboard ───────────────────────────────────────────────────────
    if tier == "Challenger":
        players = get_challenger_list()
    elif tier == "Grandmaster":
        players = get_grandmaster_list()
    else:
        players = get_master_list()

    # Sort by LP descending so we collect the highest-quality players first
    players.sort(key=lambda p: p.get("leaguePoints", 0), reverse=True)

    if max_players and len(players) > max_players:
        print(f"  Sampling top {max_players} of {len(players)} players by LP")
        players = players[:max_players]

    print(f"  Processing {len(players)} players...\n")

    new_matches: list[dict] = []
    total_skipped = 0
    start_time = time.time()

    for i, entry in enumerate(players, 1):
        puuid = entry.get("puuid")
        lp    = entry.get("leaguePoints", 0)
        if not puuid:
            continue

        # ── fetch match IDs for this player ──────────────────────────────────
        all_ids  = _matchlist(puuid, matches_per_player)
        new_ids  = [mid for mid in all_ids if mid not in existing_ids]
        skip_cnt = len(all_ids) - len(new_ids)
        total_skipped += skip_cnt

        elapsed = time.time() - start_time
        eta     = _eta(elapsed, i - 1, len(players))

        print(
            f"  [{i:>4}/{len(players)}] {lp:>5} LP | "
            f"{len(all_ids)} fetched, {skip_cnt} already known, "
            f"{len(new_ids)} new | ETA {eta}"
        )

        if dry_run:
            continue

        # ── fetch each new match detail ───────────────────────────────────────
        for mid in new_ids:
            match = _fetch_match(mid)
            if match:
                new_matches.append(match)
                existing_ids.add(mid)   # prevent cross-player duplicates

        # ── periodic checkpoint save ──────────────────────────────────────────
        if new_matches and i % SAVE_EVERY == 0:
            combined = existing_matches + new_matches
            save_json_file(path, combined)
            print(
                f"  >>> Checkpoint saved: {len(existing_matches)} + "
                f"{len(new_matches)} new = {len(combined)} total"
            )

    # ── final save ────────────────────────────────────────────────────────────
    if not dry_run and new_matches:
        combined = existing_matches + new_matches
        save_json_file(path, combined)

    total_time = time.time() - start_time
    m, s = divmod(int(total_time), 60)
    print(f"\n  Done in {m}m{s:02d}s.")
    print(f"  New matches added : {len(new_matches)}")
    print(f"  Skipped (existing): {total_skipped}")
    print(f"  Total in file     : {len(existing_matches) + len(new_matches)}")

    return len(new_matches)


# ── also rebuild meta_cache (union of all three tiers) ───────────────────────

def rebuild_meta_cache():
    print("\n  Rebuilding meta_cache.json from all three tiers...")
    seen: set[str] = set()
    merged: list[dict] = []
    for tier in ("Challenger", "Grandmaster", "Master"):
        path = RANK_FILE_MAP[tier]
        for m in load_json_file(path):
            mid = m.get("metadata", {}).get("matchId")
            if mid and mid not in seen:
                merged.append(m)
                seen.add(mid)

    meta_path = ROOT / "data" / "meta_cache.json"
    save_json_file(meta_path, merged)
    print(f"  meta_cache.json: {len(merged)} matches total")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Incremental Challenger/GM/Master match collector"
    )

    tier_group = parser.add_mutually_exclusive_group(required=True)
    tier_group.add_argument(
        "--tier",
        choices=["Challenger", "Grandmaster", "Master"],
        help="Single tier to collect",
    )
    tier_group.add_argument(
        "--all",
        action="store_true",
        help="Collect all three tiers sequentially",
    )

    parser.add_argument(
        "--matches-per-player",
        type=int,
        default=20,
        metavar="N",
        help="Recent matches to request per player (default: 20, max Riot allows: 100)",
    )
    parser.add_argument(
        "--max-players",
        type=int,
        default=None,
        metavar="N",
        help="Limit players processed (useful for Master's 10k list). "
             "Players are sorted by LP desc so you get the highest first.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fetched without making write calls",
    )
    parser.add_argument(
        "--no-meta-rebuild",
        action="store_true",
        help="Skip rebuilding meta_cache.json after collection",
    )

    args = parser.parse_args()

    tiers = (
        ["Challenger", "Grandmaster", "Master"]
        if args.all
        else [args.tier]
    )

    total_new = 0
    for tier in tiers:
        added = collect_tier(
            tier=tier,
            matches_per_player=args.matches_per_player,
            max_players=args.max_players,
            dry_run=args.dry_run,
        )
        total_new += added

    if not args.dry_run and not args.no_meta_rebuild and total_new > 0:
        rebuild_meta_cache()

    print(f"\n{'='*60}")
    print(f"  Total new matches collected: {total_new}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
