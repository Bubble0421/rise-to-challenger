"""
RAG knowledge base builder — run once before launching the dashboard.

Usage:
    cd /path/to/lol_dashboard
    python scripts/build_rag.py                    # build Challenger RAG only
    python scripts/build_rag.py --youtube          # also collect YouTube transcripts
    python scripts/build_rag.py --rebuild          # force-rebuild (clears existing data)

What it does:
  1. Loads all offline JSON match files (Challenger / Grandmaster / Master)
  2. Converts each participant into a text summary and embeds it into ChromaDB
  3. Optionally fetches YouTube transcripts for the top champions

Requirements:
  - Ollama running locally with nomic-embed-text pulled:
        ollama pull nomic-embed-text
  - youtube-transcript-api installed:
        pip install youtube-transcript-api
"""
from __future__ import annotations
import sys
import argparse
from pathlib import Path

# Make project root importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.data import load_rank_matches
from utils.rag import build_challenger_rag, add_youtube_transcript, rag_available

# ─── YouTube video catalogue ──────────────────────────────────────────────────
# Add more video IDs here as you collect them.
# Format: (video_id, champion, channel, title)
YOUTUBE_CATALOGUE: list[tuple[str, str, str, str]] = [
    # ADC guides
    ("XYZ123", "Jinx",     "ProGuides",           "Jinx ADC Guide — Laning & Teamfighting"),
    ("ABC456", "Caitlyn",  "Skill Capped",         "Caitlyn Laning — How to Dominate Lane"),
    ("DEF789", "Ezreal",   "Broken By Concept",    "Ezreal ADC Guide — Matchups & Combos"),
    # Mid
    ("GHI012", "Zed",      "ProGuides",            "Zed Mid — Full Guide Season 2025"),
    ("JKL345", "Orianna",  "Skill Capped",         "Orianna Mid — Teamfighting Masterclass"),
    # Top
    ("MNO678", "Darius",   "ProGuides",            "Darius Top — Lane Domination Guide"),
    # Jungle
    ("PQR901", "Lee Sin",  "Skill Capped",         "Lee Sin Jungle — Early Game Pathing"),
]


def _chunk_transcript(transcript: list[dict], chunk_tokens: int = 400) -> list[str]:
    """Join transcript segments into ~chunk_tokens-word chunks."""
    chunks: list[str] = []
    current: list[str] = []
    word_count = 0

    for seg in transcript:
        words = seg["text"].split()
        current.extend(words)
        word_count += len(words)
        if word_count >= chunk_tokens:
            chunks.append(" ".join(current))
            current = []
            word_count = 0

    if current:
        chunks.append(" ".join(current))
    return chunks


def collect_youtube(catalogue: list[tuple]) -> None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
    except ImportError:
        print("youtube-transcript-api not installed. Run: pip install youtube-transcript-api")
        return

    for video_id, champion, channel, title in catalogue:
        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
            chunks = _chunk_transcript(transcript)
            n = add_youtube_transcript(chunks, champion, video_id, channel, title)
            print(f"  OK {title} -> {n} chunks added")
        except (TranscriptsDisabled, NoTranscriptFound):
            print(f"  SKIP No transcript for {title} ({video_id})")
        except Exception as e:
            print(f"  ERROR for {title}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Build RAG knowledge base")
    parser.add_argument("--youtube", action="store_true", help="Also collect YouTube transcripts")
    parser.add_argument("--rebuild", action="store_true", help="Force-rebuild (clear existing data)")
    args = parser.parse_args()

    if not rag_available():
        print(
            "RAG not available. Make sure:\n"
            "   1. pip install chromadb langchain-community\n"
            "   2. ollama pull nomic-embed-text\n"
            "   3. ollama serve (running in background)"
        )
        sys.exit(1)

    print("Loading offline match data...")
    matches = load_rank_matches("Challenger")  # loads Challenger + Grand + Master
    print(f"   {len(matches)} matches loaded")

    print("Building Challenger RAG collection...")
    n = build_challenger_rag(matches, force_rebuild=args.rebuild)
    if n == 0 and not args.rebuild:
        print("   Already built (use --rebuild to regenerate)")
    else:
        print(f"   OK {n} documents embedded")

    if args.youtube:
        print("Collecting YouTube transcripts...")
        collect_youtube(YOUTUBE_CATALOGUE)

    print("\nRAG knowledge base ready at data/chromadb/")


if __name__ == "__main__":
    main()
