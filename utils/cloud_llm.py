"""Cloud LLM backend (OpenAI-compatible) with graceful opt-in.

Priority order used by callers:
  1. Cloud API   — when OPENAI_API_KEY is set (env var or Streamlit secrets)
  2. Local Ollama
  3. Deterministic fallback templates

Returns None when no key is configured or the call fails, so callers can
fall through to the next backend without special-casing errors.
"""
from __future__ import annotations

import os

DEFAULT_MODEL = "gpt-4o-mini"


def _api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return key
    try:
        import streamlit as st

        return st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        return ""


def api_available() -> bool:
    return bool(_api_key())


def api_generate(
    prompt: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = 900,
) -> str | None:
    """Single-turn generation via cloud API. None = not configured / failed."""
    key = _api_key()
    if not key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=key)
        model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or None
    except Exception:
        return None
