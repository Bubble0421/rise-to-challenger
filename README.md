# Rise to Challenger

> AI-powered League of Legends coaching — meta trends, post-game review, and counter guides powered by Master+ match data.

[![Live Demo](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://rise-to-challenger-m9ykf3u3jo5lhyzcvljcbu.streamlit.app/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-multi--agent-green.svg)](https://github.com/langchain-ai/langgraph)

**[Try the live demo →](https://rise-to-challenger-m9ykf3u3jo5lhyzcvljcbu.streamlit.app/)**

Rise to Challenger is a Streamlit-based League of Legends coaching app. It combines Riot match data, deterministic review logic, retrieval-augmented generation, and a local Ollama model to help players understand the meta, prepare matchups, and review finished games.

## What the app does

- `Meta Analysis`
  Champion tier list and hidden OP picks from 900+ Master+ matches. Filter by role, see win rate, pick rate, KDA, and confidence score.
- `Player Review`
  Search any player, benchmark every stat against Challenger averages, and get a structured AI coach report with replay checkpoints.
- `Counter Guide`
  Pre-game matchup plan with lane, mid-game, late-game, and item guidance — generated from real high-elo data in under 30 seconds.

## Quick start (no API key needed)

The live demo runs entirely in Demo Mode — no Riot API key, no local setup required.

**[Open the demo](https://rise-to-challenger-m9ykf3u3jo5lhyzcvljcbu.streamlit.app/)** and try:
1. **Meta Analysis** — search any champion, filter by role
2. **Player Review** → select Demo Mode → pick a match → generate AI coach report
3. **Counter Guide** — pick your champion and enemy, get a full game plan

## Demo Mode vs Live Mode

- `Demo Mode`
  Uses curated sample matches and timeline fixtures. Works instantly in the browser.
- `Live Mode`
  Uses Riot API lookups for real player review. Best for local development.

Set `PUBLIC_DEMO_MODE=true` in your deployment environment to default to Demo Mode.

## Tech stack

- `Streamlit` for the app UI
- `Riot API` for player, match, and timeline data
- `Ollama` for local LLM inference
- `Gemma 2 2B` as the default local generation model
- `nomic-embed-text` for embeddings
- `ChromaDB` for local RAG retrieval
- `LangGraph` for the internal multi-step coaching flow

## Architecture summary

The app does not rely on one free-form chatbot call.

Instead, the main coaching pipeline is:

`Riot API -> structured analysis -> deterministic review focus -> RAG retrieval -> local LLM generation -> validation -> final report`

This design keeps the product more explainable and reduces weak, generic, or unsupported AI advice.

## Project structure

```text
app.py                         Streamlit entry point
pages/1_Meta.py                Meta analysis page
pages/2_Player_Review.py       Post-game review page
pages/3_Counter_Guide.py       Pre-game matchup page
core/config.py                 Runtime config and model settings
integrations/                  Riot and Data Dragon API clients
services/                      Rule-based game analysis logic
features/coaching/             Agent prompts, validators, and knowledge injection
utils/                         Shared helpers for styles, LLM, RAG, data, and timeline parsing
scripts/collect_data.py        High-elo data collection
scripts/build_rag.py           Optional RAG index builder
data/                          Offline match datasets and champion rules
LoL_Architecture.pdf           Architecture overview used in presentation/demo
Launch_Dashboard.ipynb         JupyterLab launch notebook
```

## Local setup

### 1. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Add your Riot API key to `.env`:

```text
RIOT_API_KEY=your_riot_api_key
```

### 3. Start local AI services

```bash
ollama pull gemma2:2b
ollama pull nomic-embed-text
ollama serve
```

### 4. Optional: build the local RAG index

```bash
python scripts/build_rag.py
```

### 5. Run the app

```bash
streamlit run app.py
```

## Notes

- The live demo uses a 900-match sample dataset. Full local builds use 10,000+ Master+ matches.
- AI coach reports require a local Ollama instance (`gemma2:2b`). The demo falls back to deterministic rule-based analysis when Ollama is unavailable.
- The architecture PDF (`LoL_Architecture.pdf`) is included as a system design reference.
