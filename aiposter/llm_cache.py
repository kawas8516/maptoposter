"""Disk cache for model responses, keyed by normalised prompt.

Repeating a description should be instant, not another 3-second round trip and
another slice of the free-tier quota. Normalising first ("Moody  Rainy TOKYO "
and "moody rainy tokyo" are the same request) makes that hit far more often.

Stored as JSON rather than pickle: this file is written by a network response,
and security.md §7 restricts pickle to locally generated data only. JSON cannot
execute anything on load.

Cache keys are SHA-256 hashes, never the prompt text, so no user text reaches a
file path (security.md §3.3).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(os.environ.get("CACHE_DIR", "cache")) / "llm"

#: Entries older than this are ignored, so a model or prompt change eventually
#: works its way out of the cache.
MAX_AGE_SECONDS = 30 * 24 * 60 * 60

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_prompt(prompt: str) -> str:
    """Lowercase and collapse whitespace, so trivial variants share a key."""
    return _WHITESPACE_RE.sub(" ", prompt.strip().lower())


def cache_key(prompt: str, model: str, prompt_version: str = "v1") -> str:
    """Hash of the normalised prompt plus everything that changes the answer.

    The model id and a prompt version are part of the key: editing the system
    prompt or switching models must not silently serve stale responses.
    """
    material = "|".join([normalize_prompt(prompt), model, prompt_version])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def get(prompt: str, model: str, prompt_version: str = "v1") -> Optional[str]:
    """Return the cached raw model response, or ``None`` on any miss.

    Never raises: a corrupt or unreadable cache entry is a miss, not an error.
    """
    path = _path(cache_key(prompt, model, prompt_version))
    try:
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(payload.get("stored_at", 0)) > MAX_AGE_SECONDS:
            return None
        response = payload.get("response")
        return response if isinstance(response, str) else None
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None


def put(prompt: str, model: str, response: str, prompt_version: str = "v1") -> None:
    """Cache a response. Failures are ignored — caching is an optimisation."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "stored_at": time.time(),
            "model": model,
            "prompt_version": prompt_version,
            "normalized_prompt": normalize_prompt(prompt),
            "response": response,
        }
        _path(cache_key(prompt, model, prompt_version)).write_text(
            json.dumps(payload), encoding="utf-8"
        )
    except OSError:
        pass


def clear() -> int:
    """Delete every cached response. Returns how many were removed."""
    if not CACHE_DIR.is_dir():
        return 0
    removed = 0
    for path in CACHE_DIR.glob("*.json"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed
