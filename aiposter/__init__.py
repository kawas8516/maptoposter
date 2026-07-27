"""AI theming layer for AI Poster Studio.

This package sits on top of the unmodified maptoposter rendering engine. It
turns a natural-language description into a validated, legibility-guarded
theme specification; the upstream engine does all the actual rendering.
"""

__all__ = ["guards", "spec", "prompts", "llm", "fallback", "render"]
