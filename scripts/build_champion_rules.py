"""Agent-assisted champion rule builder.

This optional script drafts structured coaching rules into data/champion_rules.json.
The dashboard reads the JSON deterministically at runtime; this script is only for
expanding the rule base.

Usage:
    python scripts/build_champion_rules.py --champions Seraphine Jinx Lux
    python scripts/build_champion_rules.py --champions Seraphine --write
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.champion_rule_service import RULES_PATH  # noqa: E402


MODEL = os.environ.get("OLLAMA_MODEL", "gemma2:2b")
PHASES = ("lane", "mid_game", "teamfight", "win_condition")
ENEMY_TAGS = ("engage", "poke", "burst")
ITEM_TAGS = ("locket", "mikael", "anti_heal", "zhonya", "banshee", "ldr", "void_staff")


RULE_PROMPT = """\
Create League of Legends coaching rules for {champion}.

Return only valid JSON: a list of objects.
Each object must use this schema:
{{
  "phase": "lane|mid_game|teamfight|win_condition",
  "enemy_tags": ["engage|poke|burst"] optional,
  "item_tags": ["locket|mikael|anti_heal|zhonya|banshee|ldr|void_staff"] optional,
  "text": "one specific coach tip under 26 words"
}}

Requirements:
- Include one base rule for each phase: lane, mid_game, teamfight, win_condition.
- Include at least one rule for each enemy tag: engage, poke, burst.
- Include item-trigger rules only when the item makes sense for {champion}.
- Do not write generic advice like "play safe" or "farm well".
- Mention ability names, fight timing, spacing, wave state, objective setup, or champion job.
"""


def _load_rules() -> dict[str, list[dict]]:
    if not RULES_PATH.exists():
        return {}
    with RULES_PATH.open() as f:
        return json.load(f)


def _save_rules(rules: dict[str, list[dict]]) -> None:
    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RULES_PATH.open("w") as f:
        json.dump(rules, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _draft_rules(champion: str) -> list[dict]:
    try:
        import ollama
    except Exception as exc:
        raise RuntimeError(f"ollama package unavailable: {exc}") from exc

    response = ollama.generate(
        model=MODEL,
        prompt=RULE_PROMPT.format(champion=champion),
        options={"temperature": 0.2, "top_p": 0.9},
    )
    raw = response.get("response", "").strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON list found in model output for {champion}")
    return json.loads(raw[start : end + 1])


def _validate_rule(rule: dict) -> dict | None:
    phase = rule.get("phase")
    text = str(rule.get("text", "")).strip()
    if phase not in PHASES or not text:
        return None
    cleaned = {"phase": phase, "text": text}

    enemy_tags = [tag for tag in rule.get("enemy_tags", []) if tag in ENEMY_TAGS]
    item_tags = [tag for tag in rule.get("item_tags", []) if tag in ITEM_TAGS]
    if enemy_tags:
        cleaned["enemy_tags"] = sorted(set(enemy_tags))
    if item_tags:
        cleaned["item_tags"] = sorted(set(item_tags))
    return cleaned


def _merge_rules(existing: list[dict], drafted: list[dict]) -> list[dict]:
    merged = list(existing)
    seen = {
        (
            rule.get("phase"),
            tuple(rule.get("enemy_tags", [])),
            tuple(rule.get("item_tags", [])),
            rule.get("text"),
        )
        for rule in merged
    }
    for rule in drafted:
        valid = _validate_rule(rule)
        if not valid:
            continue
        key = (
            valid.get("phase"),
            tuple(valid.get("enemy_tags", [])),
            tuple(valid.get("item_tags", [])),
            valid.get("text"),
        )
        if key not in seen:
            merged.append(valid)
            seen.add(key)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft champion coaching rules with local Ollama.")
    parser.add_argument("--champions", nargs="+", required=True)
    parser.add_argument("--write", action="store_true", help="Write validated drafts into data/champion_rules.json.")
    args = parser.parse_args()

    rules = _load_rules()
    for champion in args.champions:
        drafted = _draft_rules(champion)
        merged = _merge_rules(rules.get(champion, []), drafted)
        print(f"{champion}: {len(rules.get(champion, []))} -> {len(merged)} rules")
        rules[champion] = merged

    if not args.write:
        print("\nPreview only. Review the drafted rules before saving.")
        print("Run again with --write to merge them into data/champion_rules.json.")
        print(json.dumps(rules, indent=2, ensure_ascii=False))
    else:
        _save_rules(rules)
        print(f"Saved {RULES_PATH}")


if __name__ == "__main__":
    main()
