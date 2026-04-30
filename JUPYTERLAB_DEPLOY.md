# JupyterLab Deployment Guide

This guide shows the simplest way to run `Rise to Challenger` inside JupyterLab or JupyterHub.

## Option 1: Use the included notebook

Open:

- `Launch_Dashboard.ipynb`

Then run the cells from top to bottom. The notebook helps you:

- install dependencies
- write a local `.env`
- check Ollama
- start Streamlit
- print the correct access URL

This is the easiest option if you want a guided setup.

## Option 2: Use the terminal inside JupyterLab

### 1. Open a terminal

In JupyterLab:

- `File -> New -> Terminal`

### 2. Go to the project folder

```bash
cd /path/to/lol_dashboard
```

### 3. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Create `.env`

```bash
cp .env.example .env
```

Edit `.env` and add your Riot API key.

### 5. Start Ollama

Make sure Ollama is installed on the server, then run:

```bash
ollama pull gemma2:2b
ollama pull nomic-embed-text
ollama serve
```

If your Jupyter server already has Ollama running, you do not need to start it again.

### 6. Start Streamlit

```bash
bash scripts/start_streamlit.sh
```

This starts the app on port `8510` and writes logs to `streamlit.log`.

### 7. Open the app

If you are using plain JupyterLab on your own machine, open:

```text
http://localhost:8510
```

If you are using JupyterHub or a remote server with proxy support, the URL is usually:

```text
https://<your-jupyter-server>/proxy/8510/
```

If the included notebook prints a proxy URL, use that exact URL.

## Common problems

### Riot API says unauthorized

Your Riot development key may have expired. Replace `RIOT_API_KEY` in `.env` with a fresh key.

### AI coach says local model unavailable

Ollama is not running, or the required model is missing.

Check:

```bash
ollama list
curl http://localhost:11434/api/tags
```

### Streamlit page does not load

Check whether the process is running:

```bash
cat streamlit.pid
ps -p "$(cat streamlit.pid)"
tail -n 80 streamlit.log
```

## Stop the app

```bash
if [ -f streamlit.pid ]; then kill "$(cat streamlit.pid)"; rm streamlit.pid; fi
```
