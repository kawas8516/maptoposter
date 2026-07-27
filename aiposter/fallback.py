"""Offline fallback: pick the closest stock theme for a description.

This is the last rung of the ladder in :mod:`aiposter.llm`. When the hosted
model is unreachable, out of credits, or produces JSON that will not validate
even after a repair round-trip, the user still gets a poster — just one themed
from the existing catalogue rather than a newly invented palette.

Deliberately dumb and fully deterministic: keyword hits against a hand-authored
map, plus token overlap with each theme's own name and description. No network,
no model, trivially unit-testable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"

#: Hand-authored mood keywords per stock theme. These carry more weight than
#: incidental token overlap because a theme's own description rarely contains
#: the words people actually reach for ("moody", "rainy", "cyberpunk").
KEYWORDS: dict[str, tuple[str, ...]] = {
    "noir": ("noir", "black", "monochrome", "moody", "dark", "gallery", "stark", "night", "shadow"),
    "midnight_blue": ("midnight", "navy", "deep", "blue", "night", "dusk", "evening", "twilight"),
    "neon_cyberpunk": ("neon", "cyberpunk", "electric", "futuristic", "glow", "synthwave", "vivid", "tokyo"),
    "japanese_ink": ("ink", "japanese", "zen", "minimal", "brush", "sumi", "calm", "quiet"),
    "blueprint": ("blueprint", "technical", "architectural", "drafting", "schematic", "engineering"),
    "terracotta": ("terracotta", "clay", "mediterranean", "warm", "earthy", "adobe", "rust"),
    "sunset": ("sunset", "golden", "dusk", "peach", "warm", "orange", "pink", "dreamy"),
    "autumn": ("autumn", "fall", "amber", "harvest", "leaves", "rust", "copper"),
    "ocean": ("ocean", "sea", "marine", "coastal", "harbour", "harbor", "wave", "nautical"),
    "forest": ("forest", "woods", "pine", "green", "nature", "moss", "woodland"),
    "emerald": ("emerald", "jewel", "rich", "verdant", "gem"),
    "pastel_dream": ("pastel", "soft", "dreamy", "gentle", "candy", "light", "airy"),
    "warm_beige": ("beige", "sand", "neutral", "cream", "muted", "linen", "understated"),
    "copper_patina": ("copper", "patina", "verdigris", "bronze", "aged", "oxidised", "oxidized"),
    "monochrome_blue": ("monochrome", "tonal", "single", "cool", "steel", "slate"),
    "contrast_zones": ("contrast", "bold", "graphic", "punchy", "high-contrast", "striking"),
    "gradient_roads": ("gradient", "fade", "blend", "smooth", "transition"),
}

_TOKEN_RE = re.compile(r"[a-z]+")

#: Deterministic tie-break: earlier themes win ties. Ordered so the most
#: broadly-applicable moods sit first.
_PRIORITY: tuple[str, ...] = (
    "noir",
    "midnight_blue",
    "neon_cyberpunk",
    "sunset",
    "terracotta",
    "ocean",
    "forest",
    "japanese_ink",
    "blueprint",
    "warm_beige",
    "pastel_dream",
    "autumn",
    "emerald",
    "copper_patina",
    "monochrome_blue",
    "contrast_zones",
    "gradient_roads",
)

#: Words too common to carry signal in the overlap score.
_STOPWORDS = frozenset(
    "a an and the of with in on at for to from is are be by into over under "
    "very quite really some more most it its this that these those city map "
    "poster theme colour color colours colors style look feel vibe".split()
)


def _tokenize(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2}


def available_themes() -> list[str]:
    """Stock theme names, sorted."""
    if not THEMES_DIR.is_dir():
        return []
    return sorted(p.stem for p in THEMES_DIR.glob("*.json"))


def load_stock_theme(name: str) -> dict:
    """Read a stock theme file. Raises if it does not exist."""
    path = THEMES_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def score_themes(description: str) -> dict[str, float]:
    """Score every stock theme against a description. Higher is a better match."""
    tokens = _tokenize(description)
    scores: dict[str, float] = {}

    for name in available_themes():
        score = 0.0
        for keyword in KEYWORDS.get(name, ()):
            if keyword in tokens:
                score += 3.0
        try:
            theme = load_stock_theme(name)
        except (OSError, json.JSONDecodeError):
            scores[name] = score
            continue
        blurb = f"{theme.get('name', '')} {theme.get('description', '')}"
        score += len(tokens & _tokenize(blurb))
        scores[name] = score

    return scores


def nearest_stock_theme(description: str) -> tuple[str, dict]:
    """Return ``(theme_name, theme_dict)`` for the best-matching stock theme.

    Falls back to ``terracotta`` (the renderer's own default) when nothing
    scores above zero.
    """
    scores = score_themes(description)
    if not scores:
        raise FileNotFoundError(f"no stock themes found in {THEMES_DIR}")

    best = max(scores.values())
    if best <= 0:
        name = "terracotta" if "terracotta" in scores else sorted(scores)[0]
        return name, load_stock_theme(name)

    winners = [n for n, s in scores.items() if s == best]
    for candidate in _PRIORITY:
        if candidate in winners:
            return candidate, load_stock_theme(candidate)
    name = sorted(winners)[0]
    return name, load_stock_theme(name)
