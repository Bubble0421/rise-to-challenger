"""
RAG knowledge base — ChromaDB + Ollama embeddings.

Two collections:
  challenger_matches  — text summaries built from offline match JSON
  youtube_guides      — champion-guide transcripts (populated by scripts/build_rag.py)

All functions degrade gracefully if ChromaDB / nomic-embed-text are unavailable.
"""
from __future__ import annotations

from core.config import CHROMA_DIR, EMBEDDING_MODEL

CHALLENGER_COLLECTION = "challenger_matches"
YOUTUBE_COLLECTION = "youtube_guides"

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


# ─── Public API ───────────────────────────────────────────────────────────────

def search_rag(query: str, collection: str = CHALLENGER_COLLECTION, k: int = 3) -> list[dict]:
    """
    Similarity search.  Returns list of {content, source, champion}.
    Returns [] if ChromaDB / embedding model unavailable.
    """
    store = _get_store(collection)
    if store is None:
        return []
    try:
        docs = store.similarity_search(query, k=k)
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
            cs_per_min = round(
                (p["totalMinionsKilled"] + p.get("neutralMinionsKilled", 0)) / max(game_min, 1), 1
            )
            kda = round((p["kills"] + p["assists"]) / max(p["deaths"], 1), 2)
            items = ", ".join(
                str(p.get(f"item{i}", 0))
                for i in range(6)
                if p.get(f"item{i}", 0) != 0
            )
            text = (
                f"Challenger {p['championName']} {pos} {'WIN' if p['win'] else 'LOSS'} — "
                f"KDA {p['kills']}/{p['deaths']}/{p['assists']} (ratio {kda}), "
                f"CS/min {cs_per_min}, damage {p['totalDamageDealtToChampions']:,}, "
                f"vision {p['visionScore']}, duration {round(game_min)}min, "
                f"items [{items}]"
            )
            docs.append(
                Document(
                    page_content=text,
                    metadata={
                        "champion": p["championName"],
                        "position": pos,
                        "win": str(p["win"]),
                        "source": "Challenger match data",
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
