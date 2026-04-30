# Rise to Challenger

Rise to Challenger is a Streamlit-based League of Legends coaching app. It combines Riot match data, deterministic review logic, retrieval-augmented generation, and a local Ollama model to help players understand the meta, prepare matchups, and review finished games.

This public version also includes a **Demo Mode** for portfolio deployment. Demo Mode uses curated sample matches so the app can be shown without a live Riot API key or large local ranked archives.

## What the app does

- `Meta Analysis`
  Search champions and inspect Master+ trends such as tier, win rate, pick rate, KDA, and confidence.
- `Player Review`
  Review either curated sample matches or live Riot matches, compare one game against Challenger benchmarks, and generate an AI coach report with replay checkpoints and follow-up chat.
- `Counter Guide`
  Build a pre-game matchup plan with lane, mid-game, late-game, and item guidance.

## Public repo note

This GitHub version is trimmed for public sharing.

Large offline ranked datasets are not included in the repository because they exceed practical GitHub limits and make the project unnecessarily heavy to clone. The app can still run in **Demo Mode** without them, and you can rebuild the larger local datasets for full offline analysis.

See [data/README.md](data/README.md) for rebuilding those files locally.

## Demo Mode vs Live Mode

- `Demo Mode`
  Uses curated sample matches and timeline fixtures. Best for public GitHub links and Streamlit deployments.
- `Live Mode`
  Uses Riot API lookups for real player review. Best for local development and private demos.

Set `PUBLIC_DEMO_MODE=true` in your deployment environment if you want the app to default to Demo Mode.

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

## JupyterLab deployment

This project already includes a notebook launcher:

- `Launch_Dashboard.ipynb`

If you want a step-by-step text guide, see:

- [JUPYTERLAB_DEPLOY.md](JUPYTERLAB_DEPLOY.md)

## GitHub publishing checklist

Before pushing this project publicly:

1. Make sure `.env` is not committed.
2. Do not commit `data/chromadb/`, `rise_to_challenger.zip`, logs, or local cache files.
3. Refresh the Riot API key locally after pushing if you ever pasted a real key into a notebook or config file.
4. Keep large generated artifacts out of the repo.

## Suggested GitHub repo setup

```bash
git init
git add .
git commit -m "Initial public release of Rise to Challenger"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

## Notes

- `Meta Analysis` and `Counter Guide` need local offline data files for full functionality.
- `Player Review` needs a valid Riot API key for live summoner and match lookup.
- AI outputs degrade gracefully if Ollama or the RAG index is unavailable.
- The architecture PDF is included because it is part of the project presentation and system explanation.
