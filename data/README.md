# Data Directory

This public repository does not include the large ranked match datasets used for offline meta analysis and matchup aggregation.

Those files are intentionally excluded because:

- several files are larger than GitHub's normal file size limits
- they make the repository much heavier to clone
- they contain raw high-elo match payloads that are better generated locally

## Files not included publicly

Typical local files may include:

- `challenger_matches.json`
- `grandmaster_matches.json`
- `master_matches.json`
- `meta_cache.json`
- `chromadb/`

## How to rebuild locally

1. Add a valid `RIOT_API_KEY` to `.env`
2. Run:

```bash
python scripts/collect_data.py
```

3. Optional: rebuild the local RAG index

```bash
python scripts/build_rag.py
```

After that, `Meta Analysis` and `Counter Guide` will use your local offline data.
