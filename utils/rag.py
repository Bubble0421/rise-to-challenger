"""
RAG knowledge base — ChromaDB + Ollama embeddings.

Two collections:
  challenger_matches  — BEHAVIORAL NARRATIVES built from offline match JSON.
                        Not stat lines (CS/min, KDA, vision) — those the
                        deterministic engine already computes. Instead, each doc
                        describes what a Challenger player *did*: how they won
                        lane, when they roamed, how they converted leads into
                        objectives, and how disciplined their deaths were.
  youtube_guides      — champion-guide transcripts (populated by scripts/build_rag.py)

All functions degrade gracefully if ChromaDB / nomic-embed-text are unavailable:
retrieval falls back to keyword scoring over a committed narrative corpus so the
demo still surfaces behavioral context on hosts with no embedding model.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from core.config import CHROMA_DIR, EMBEDDING_MODEL

CHALLENGER_COLLECTION = "challenger_matches"
YOUTUBE_COLLECTION = "youtube_guides"

# Pre-built behavioral-narrative corpus, committed to the repo. Lets retrieval
# surface *what Challenger players did* even on hosts with no embedding model
# (e.g. Streamlit Cloud), via the keyword fallback below.
NARRATIVES_FILE = Path(__file__).resolve().parent.parent / "data" / "challenger_narratives.json"

_stores: dict = {}   # collection_name → Chroma instance


# ─── Internals ────────────────────────────────────────────────────────────────

def _embeddings():
    try:
        from langchain_ollama import OllamaEmbeddings
        return OllamaEmbeddings(model=EMBEDDING_MODEL)
    except Exception:
        return None


def _get_store(collection: str):
    if collection in _stores:
        return _stores[collection]
    try:
        try:
            from langchain_chroma import Chroma
        except ImportError:
            from langchain_community.vectorstores import Chroma
        emb = _embeddings()
        if emb is None:
            return None
        store = Chroma(
            collection_name=collection,
            embedding_function=emb,
            persist_directory=CHROMA_DIR,
        )
        _stores[collection] = store
        return store
    except Exception as e:
        print(f"[RAG] ChromaDB unavailable ({collection}): {e}")
        return None


# ─── Behavioral narrative builder ─────────────────────────────────────────────
# The core of the RAG rewrite. A match summary's `challenges` block records what
# the player actually DID; we turn it into prose a coach would recognise, so the
# retriever matches on *behavior* ("roamed after shoving", "converted a lead into
# dragons", "controlled deaths") instead of on numbers the app already computes.

def _ch(p: dict, key: str, default: float = 0.0) -> float:
    return p.get("challenges", {}).get(key, default)


def build_behavior_narrative(p: dict, game_min: float) -> str:
    """Return a behavioral narrative for one participant, or '' if the summary is
    too thin (no `challenges` block) to say anything beyond raw stats."""
    ch = p.get("challenges") or {}
    if not ch:
        return ""

    champ = p.get("championName", "Unknown")
    pos = p.get("teamPosition", "UNKNOWN")
    result = "won" if p.get("win") else "lost"
    parts: list[str] = [f"Challenger {champ} {pos} {result} this game."]

    # ── Lane phase: how they won or lost the early game ──
    cs_adv = _ch(p, "maxCsAdvantageOnLaneOpponent")
    lvl_lead = _ch(p, "maxLevelLeadLaneOpponent")
    plates = _ch(p, "turretPlatesTaken")
    lane_gold = _ch(p, "laningPhaseGoldExpAdvantage") or _ch(p, "earlyLaningPhaseGoldExpAdvantage")
    if cs_adv >= 20:
        parts.append(f"Dominated lane with a peak {int(cs_adv)} CS lead over their opponent"
                     + (f" and a {int(lvl_lead)}-level lead" if lvl_lead >= 1 else "")
                     + (f", cashing it into {int(plates)} turret plates." if plates >= 1 else "."))
    elif cs_adv <= -20:
        parts.append(f"Fell behind in lane by up to {int(abs(cs_adv))} CS but stayed in the game.")
    elif plates >= 5:
        parts.append(f"Traded evenly in CS but pressured the tower for {int(plates)} plates.")
    elif lane_gold and lane_gold < -500:
        parts.append("Conceded the laning phase and played for scaling instead of forcing trades.")

    # ── Aggression / roams: solo kills and skirmishing ──
    solo = _ch(p, "soloKills")
    near_turret = _ch(p, "killsNearEnemyTurret")
    early_td = _ch(p, "takedownsBeforeJungleMinionSpawn")
    if solo >= 2:
        parts.append(f"Created pressure themselves with {int(solo)} solo kills"
                     + (f", {int(near_turret)} of them by diving under the enemy turret." if near_turret >= 1 else "."))
    if early_td >= 1:
        parts.append("Started the game proactively, taking a level-1 invade or early skirmish.")

    # ── Objectives: converting advantage into the map ──
    dragons = _ch(p, "dragonTakedowns")
    heralds = _ch(p, "riftHeraldTakedowns")
    barons = _ch(p, "baronTakedowns")
    obj_dmg = p.get("damageDealtToObjectives", 0)
    steals = p.get("objectivesStolen", 0) or _ch(p, "epicMonsterSteals")
    obj_bits = []
    if dragons >= 2:
        obj_bits.append(f"{int(dragons)} dragons")
    if heralds >= 1:
        obj_bits.append(f"{int(heralds)} herald")
    if barons >= 1:
        obj_bits.append(f"{int(barons)} baron")
    if obj_bits:
        parts.append("Showed up for objectives — part of " + ", ".join(obj_bits) + ".")
    if steals >= 1:
        parts.append(f"Stole {int(steals)} epic monster off the enemy with a contest.")

    # ── Death discipline: not just how many, but the shape of them ──
    deaths = p.get("deaths", 0)
    time_dead = p.get("totalTimeSpentDead", 0)
    under_turret = _ch(p, "killsUnderOwnTurret")
    if deaths == 0:
        parts.append("Played a clean game with zero deaths, never handing the enemy tempo.")
    elif deaths <= 3 and game_min >= 25:
        parts.append(f"Kept deaths low ({deaths}) despite a {int(game_min)}-minute game, respecting fog and cooldowns.")
    elif deaths >= 7:
        parts.append(f"Died {deaths} times ({int(time_dead)}s spent dead) — even a Challenger bled tempo here.")
    if under_turret >= 1:
        parts.append("Used their own turret to turn ganks into kills defensively.")

    # ── Teamfighting role: how they showed up in fights ──
    team_dmg = _ch(p, "teamDamagePercentage")
    dmg_taken = _ch(p, "damageTakenOnTeamPercentage")
    cc = p.get("timeCCingOthers", 0)
    if team_dmg >= 0.30:
        parts.append(f"Was the fight carry, dealing {team_dmg*100:.0f}% of team damage"
                     + (f" while taking only {dmg_taken*100:.0f}%." if dmg_taken and dmg_taken < 0.2 else "."))
    elif dmg_taken >= 0.28:
        parts.append(f"Played frontline, absorbing {dmg_taken*100:.0f}% of the damage their team took"
                     + (f" and locking targets down for {int(cc)}s of crowd control." if cc >= 10 else "."))
    elif cc >= 25:
        parts.append(f"Enabled fights with {int(cc)}s of crowd control on enemies.")

    # ── Vision behavior ──
    control_wards = p.get("detectorWardsPlaced", 0) or _ch(p, "controlWardsPlaced")
    ward_kills = p.get("wardsKilled", 0) or _ch(p, "wardTakedowns")
    if control_wards >= 4:
        parts.append(f"Backed up objectives with {int(control_wards)} control wards"
                     + (f" and cleared {int(ward_kills)} enemy wards." if ward_kills >= 3 else "."))
    elif ward_kills >= 4:
        parts.append(f"Denied enemy vision by clearing {int(ward_kills)} wards before fights.")

    # A one-line narrative is not worth embedding; require real behavioral signal.
    return " ".join(parts) if len(parts) >= 3 else ""


# ─── Keyword-retrieval fallback (no embedding model required) ──────────────────

_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
         "how", "they", "their", "them", "still", "played", "well", "game",
         "into", "up", "at", "by", "was", "were", "is", "are", "this", "that"}


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in _STOP and len(t) > 2]


@lru_cache(maxsize=1)
def _load_narratives() -> tuple:
    """Load the committed behavioral-narrative corpus (tuple for lru_cache)."""
    if not NARRATIVES_FILE.exists():
        return ()
    try:
        with NARRATIVES_FILE.open() as f:
            return tuple(json.load(f))
    except Exception:
        return ()


def _keyword_search(query: str, k: int) -> list[dict]:
    """Score narratives by term overlap with the query. Cheap, deterministic, and
    dependency-free — the graceful-degradation path when embeddings are absent."""
    corpus = _load_narratives()
    if not corpus:
        return []
    q_terms = set(_tokenize(query))
    if not q_terms:
        return []
    scored = []
    for doc in corpus:
        d_terms = set(_tokenize(doc.get("content", "")))
        if not d_terms:
            continue
        overlap = len(q_terms & d_terms)
        if not overlap:
            continue
        score = overlap / (len(q_terms) ** 0.5)
        # Boost same-champion narratives: "how a Challenger on YOUR champion
        # played this spot" is more useful than a generic role example.
        champ = doc.get("champion", "").lower()
        if champ and champ in q_terms:
            score += 1.5
        scored.append((score, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "content": doc.get("content", ""),
            "source": doc.get("source", "Challenger behavioral narrative"),
            "champion": doc.get("champion", ""),
            "channel": "",
            "video_id": "",
        }
        for _, doc in scored[:k]
    ]


# ─── Public API ───────────────────────────────────────────────────────────────

def search_rag(query: str, collection: str = CHALLENGER_COLLECTION, k: int = 3) -> list[dict]:
    """
    Behavioral similarity search. Returns list of {content, source, champion}.

    Tries the embedding-backed vector store first. If it is unavailable or empty
    (e.g. Streamlit Cloud with no Ollama), falls back to keyword scoring over the
    committed narrative corpus so retrieval still returns behavioral context.
    """
    store = _get_store(collection)
    if store is not None:
        try:
            docs = store.similarity_search(query, k=k)
            if docs:
                return [
                    {
                        "content": doc.page_content,
                        "source": doc.metadata.get("source", "Challenger data"),
                        "champion": doc.metadata.get("champion", ""),
                        "channel": doc.metadata.get("channel", ""),
                        "video_id": doc.metadata.get("video_id", ""),
                    }
                    for doc in docs
                ]
        except Exception:
            pass

    # Fallback: keyword retrieval over the committed behavioral narratives.
    if collection == CHALLENGER_COLLECTION:
        return _keyword_search(query, k)
    return []


def build_challenger_rag(matches: list, force_rebuild: bool = False) -> int:
    """
    Populate the challenger_matches collection from offline match JSON.
    Returns number of documents added.
    Skips if collection already has data and force_rebuild=False.
    """
    store = _get_store(CHALLENGER_COLLECTION)
    if store is None:
        return 0

    # Check if already populated using the public LangChain get() API
    if not force_rebuild:
        try:
            existing = store.get(limit=1)
            if existing and existing.get("ids"):
                return 0  # already built
        except Exception:
            pass

    from langchain_core.documents import Document

    docs: list[Document] = []
    for match in matches:
        game_min = match["info"]["gameDuration"] / 60
        for p in match.get("info", {}).get("participants", []):
            pos = p.get("teamPosition")
            if not pos or pos == "UNKNOWN":
                continue
            # Embed the BEHAVIORAL narrative, not the stat line. Summaries without
            # a challenges block yield no narrative and are skipped.
            text = build_behavior_narrative(p, game_min)
            if not text:
                continue
            docs.append(
                Document(
                    page_content=text,
                    metadata={
                        "champion": p["championName"],
                        "position": pos,
                        "win": str(p["win"]),
                        "source": "Challenger behavioral narrative",
                        "match_id": match.get("metadata", {}).get("matchId", ""),
                    },
                )
            )

    if docs:
        # Batch in chunks of 500 to avoid memory spikes
        batch = 500
        for i in range(0, len(docs), batch):
            store.add_documents(docs[i : i + batch])
    return len(docs)


def add_youtube_transcript(
    transcript_chunks: list[str],
    champion: str,
    video_id: str,
    channel: str,
    title: str,
) -> int:
    """Add YouTube transcript chunks to the youtube_guides collection."""
    store = _get_store(YOUTUBE_COLLECTION)
    if store is None:
        return 0

    from langchain_core.documents import Document

    docs = [
        Document(
            page_content=chunk,
            metadata={
                "champion": champion,
                "video_id": video_id,
                "channel": channel,
                "title": title,
                "source": f"{channel}: \"{title}\" (YouTube)",
            },
        )
        for chunk in transcript_chunks
        if chunk.strip()
    ]
    if docs:
        store.add_documents(docs)
    return len(docs)


def rag_available() -> bool:
    """Quick check — True if ChromaDB + nomic-embed-text reachable."""
    try:
        __import__("chromadb")
        from langchain_ollama import OllamaEmbeddings  # noqa: F401
        return True
    except Exception:
        return False
