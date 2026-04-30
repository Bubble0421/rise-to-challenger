"""Central application configuration.

Keep runtime constants here so Riot, DDragon, RAG, and coaching code do not
drift into different patch/model settings.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

RIOT_API_KEY = os.getenv("RIOT_API_KEY", "")

REGION = os.getenv("RIOT_REGION", "na1")
REGIONAL = os.getenv("RIOT_REGIONAL", "americas")
QUEUE_TYPE = "RANKED_SOLO_5x5"
QUEUE_RANKED_SOLO = 420

PATCH = os.getenv("DDRAGON_PATCH", "16.7.1")
DATA_PATCH_LABEL = os.getenv("DATA_PATCH_LABEL", "16.6-16.7")

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma2:2b")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
CHROMA_DIR = str(Path(os.environ.get("CHROMA_DIR", "data/chromadb")))

CHALL_AVG_ITEM_MIN = 13    # Challenger average first legendary item completion (minutes)
