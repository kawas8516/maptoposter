"""Hosted-model client for turning a description into a validated PosterSpec.

The ladder, in order, with the user always ending up with *something*:

1. Ask the primary model.
2. If the JSON does not validate, one repair round-trip carrying only the
   validation error back to the model.
3. If that fails, the same two steps against a backup model.
4. If that fails, an offline keyword match to the nearest stock theme.

Model choice (checked against the Hub API):

* ``Qwen/Qwen2.5-7B-Instruct`` is ungated and served live by Together and
  Featherless-ai for the ``conversational`` task.
* ``Qwen/Qwen2.5-72B-Instruct`` is ungated and served by DeepInfra, used as the
  backup.
* ``meta-llama/Llama-3.1-8B-Instruct`` is deliberately *not* used: it is
  ``gated: "manual"``, so calls fail until a licence is accepted and manually
  approved.

Because the task is ``conversational`` we call ``chat_completion``, not
``text_generation``.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import ValidationError

from . import fallback, llm_cache, prompts
from .spec import PosterSpec, response_format
from .timing import Timings

PRIMARY_MODEL = "Qwen/Qwen2.5-7B-Instruct"
BACKUP_MODEL = "Qwen/Qwen2.5-72B-Instruct"

#: Seconds before a single inference call is abandoned (security.md §5).
REQUEST_TIMEOUT = 60.0

#: Greedy decoding. The same description should produce the same palette — that
#: makes the evaluation harness reproducible and makes the response cache
#: meaningful. Palette variety comes from the description, not from sampling.
TEMPERATURE = 0.0

#: A PosterSpec is ~350 tokens of compact JSON. Capping here bounds both latency
#: and the damage a runaway generation can do to the free-tier quota.
MAX_TOKENS = 500

#: Bumped whenever the system prompt or schema changes, so cached responses from
#: an older prompt are not reused.
PROMPT_VERSION = "v1"

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class PromptTooLongError(ValueError):
    """Raised when the description exceeds the hard input cap."""


@dataclass
class Attempt:
    """One round-trip to a model, recorded for the evaluation harness."""

    model: str
    kind: str  # "initial" | "repair"
    ok: bool
    error: Optional[str] = None
    latency_ms: float = 0.0

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "kind": self.kind,
            "ok": self.ok,
            "error": self.error,
            "latency_ms": round(self.latency_ms, 1),
        }


@dataclass
class GenerationTrace:
    """Everything FR5 needs to compute validity, repair and latency rates."""

    description: str
    attempts: list[Attempt] = field(default_factory=list)
    source: str = "pending"  # first | repair | backup | backup_repair | fallback
    fallback_theme: Optional[str] = None
    cache_hit: bool = False

    @property
    def first_attempt_valid(self) -> bool:
        return bool(self.attempts) and self.attempts[0].ok

    @property
    def repair_attempted(self) -> bool:
        return any(a.kind == "repair" for a in self.attempts)

    @property
    def repair_succeeded(self) -> bool:
        return any(a.kind == "repair" and a.ok for a in self.attempts)

    @property
    def backup_used(self) -> bool:
        return any(a.model == BACKUP_MODEL for a in self.attempts)

    @property
    def fallback_used(self) -> bool:
        return self.source == "fallback"

    @property
    def llm_ms(self) -> float:
        return sum(a.latency_ms for a in self.attempts)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "cache_hit": self.cache_hit,
            "first_attempt_valid": self.first_attempt_valid,
            "repair_attempted": self.repair_attempted,
            "repair_succeeded": self.repair_succeeded,
            "backup_used": self.backup_used,
            "fallback_used": self.fallback_used,
            "fallback_theme": self.fallback_theme,
            "llm_ms": round(self.llm_ms, 1),
            "attempts": [a.as_dict() for a in self.attempts],
        }


@dataclass
class GenerationResult:
    """A theme plus how we got there.

    ``spec`` is ``None`` only on the fallback path, where no model output was
    usable and therefore no city or country could be inferred — the UI asks the
    user to supply those.
    """

    theme: dict
    spec: Optional[PosterSpec]
    trace: GenerationTrace
    timings: Timings = field(default_factory=Timings)

    @property
    def city(self) -> Optional[str]:
        return self.spec.city if self.spec else None

    @property
    def country(self) -> Optional[str]:
        return self.spec.country if self.spec else None

    @property
    def distance(self) -> Optional[int]:
        return self.spec.distance if self.spec else None


def resolve_token() -> Optional[str]:
    """Find the Hugging Face token without ever logging it.

    Order: ``HF_TOKEN`` env var, then Streamlit secrets, then ``None`` — in
    which case ``InferenceClient`` falls back to the token cached by
    ``huggingface-cli login``. Never hardcoded (security.md §2).
    """
    for var in ("HF_TOKEN", "HUGGINGFACEHUB_API_TOKEN"):
        value = os.environ.get(var)
        if value:
            return value

    try:  # Streamlit is optional; this module must stay importable headless.
        import streamlit as st

        secret = st.secrets.get("HF_TOKEN")  # type: ignore[union-attr]
        if secret:
            return str(secret)
    except Exception:
        pass

    return None


def extract_json(raw: str) -> str:
    """Pull the JSON object out of a model response.

    Instructed not to, models still occasionally wrap output in code fences or
    add a sentence of preamble.
    """
    text = _FENCE_RE.sub("", raw.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return text.strip()
    return text[start:end + 1]


def _validate(raw: str) -> PosterSpec:
    """Parse and validate model output. Never ``eval`` (security.md §4)."""
    return PosterSpec.model_validate(json.loads(extract_json(raw)))


def _error_text(exc: Exception) -> str:
    """A validation message safe to send back to the model.

    Only the validator's own complaint — no stack trace, no paths, nothing
    about the environment (security.md §4).
    """
    if isinstance(exc, ValidationError):
        parts = [
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]
        return "\n".join(parts[:12])
    if isinstance(exc, json.JSONDecodeError):
        return f"Response was not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})"
    return "Response could not be parsed as a JSON object."


class ThemeGenerator:
    """Wraps ``InferenceClient`` with the validate/repair/fallback ladder."""

    def __init__(
        self,
        primary_model: str = PRIMARY_MODEL,
        backup_model: str = BACKUP_MODEL,
        timeout: float = REQUEST_TIMEOUT,
        token: Optional[str] = None,
        use_response_format: bool = True,
        use_cache: bool = True,
    ) -> None:
        self.primary_model = primary_model
        self.backup_model = backup_model
        self.timeout = timeout
        self._token = token if token is not None else resolve_token()
        self._use_response_format = use_response_format
        self._use_cache = use_cache
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from huggingface_hub import InferenceClient

            self._client = InferenceClient(token=self._token, timeout=self.timeout)
        return self._client

    def _call(self, model: str, messages: list[dict[str, str]]) -> str:
        """One chat completion. Structured output is best-effort only.

        Provider support for ``response_format`` varies, so a rejection is
        retried once without it — the prompt, not the provider feature, is what
        actually keeps output on-schema.
        """
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
        }

        if self._use_response_format:
            try:
                completion = client.chat_completion(**kwargs, response_format=response_format())
                return completion.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001 - provider errors are opaque
                if "response_format" not in str(exc).lower() and "json_schema" not in str(exc).lower():
                    raise
                self._use_response_format = False

        completion = client.chat_completion(**kwargs)
        return completion.choices[0].message.content or ""

    def _try_model(
        self, model: str, description: str, trace: GenerationTrace, source_tag: str
    ) -> Optional[PosterSpec]:
        """Initial call plus at most one repair against a single model."""
        # A previously seen description skips the network entirely. Only the
        # initial call is cached: a repair is conditioned on a specific bad
        # response, so it has no meaning outside that exchange.
        if self._use_cache:
            cached = llm_cache.get(description, model, PROMPT_VERSION)
            if cached is not None:
                try:
                    spec = _validate(cached)
                    trace.attempts.append(Attempt(model, "cached", True, None, 0.0))
                    trace.cache_hit = True
                    trace.source = source_tag
                    return spec
                except (ValidationError, json.JSONDecodeError, ValueError):
                    pass  # stale or unusable entry; fall through to a live call

        started = time.perf_counter()
        try:
            raw = self._call(model, prompts.build_messages(description))
        except Exception as exc:  # noqa: BLE001 - network/provider failure
            trace.attempts.append(
                Attempt(model, "initial", False, _network_error(exc), _ms(started))
            )
            return None

        try:
            spec = _validate(raw)
            trace.attempts.append(Attempt(model, "initial", True, None, _ms(started)))
            trace.source = source_tag
            if self._use_cache:
                llm_cache.put(description, model, raw, PROMPT_VERSION)
            return spec
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            error = _error_text(exc)
            trace.attempts.append(Attempt(model, "initial", False, error, _ms(started)))

        # One repair round-trip, carrying only the validation error.
        started = time.perf_counter()
        try:
            repaired = self._call(model, prompts.repair_messages(description, raw, error))
        except Exception as exc:  # noqa: BLE001
            trace.attempts.append(
                Attempt(model, "repair", False, _network_error(exc), _ms(started))
            )
            return None

        try:
            spec = _validate(repaired)
            trace.attempts.append(Attempt(model, "repair", True, None, _ms(started)))
            trace.source = f"{source_tag}_repair" if source_tag != "first" else "repair"
            # Cache the repaired output under the description: it is a valid
            # response for this prompt, so a repeat should skip both round trips.
            if self._use_cache:
                llm_cache.put(description, model, repaired, PROMPT_VERSION)
            return spec
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            trace.attempts.append(Attempt(model, "repair", False, _error_text(exc), _ms(started)))
            return None

    def generate(self, description: str) -> GenerationResult:
        """Run the full ladder. Always returns a usable theme."""
        description = description.strip()
        if not description:
            raise ValueError("description is empty")
        if len(description) > prompts.MAX_PROMPT_CHARS:
            raise PromptTooLongError(
                f"description is {len(description)} characters; "
                f"the limit is {prompts.MAX_PROMPT_CHARS}"
            )

        trace = GenerationTrace(description=description)
        timings = Timings()

        started = time.perf_counter()
        for model, tag in ((self.primary_model, "first"), (self.backup_model, "backup")):
            spec = self._try_model(model, description, trace, tag)
            if spec is not None:
                # Validation happens inside the call path; attribute the network
                # time to the model and the remainder to validation.
                timings.record("llm_ms", trace.llm_ms, "cache hit" if trace.cache_hit else "")
                timings.record("validate_ms", max(_ms(started) - trace.llm_ms, 0.0))
                return GenerationResult(
                    theme=spec.theme.to_theme_dict(), spec=spec, trace=trace, timings=timings
                )

        name, theme = fallback.nearest_stock_theme(description)
        trace.source = "fallback"
        trace.fallback_theme = name
        timings.record("llm_ms", trace.llm_ms)
        timings.record("validate_ms", max(_ms(started) - trace.llm_ms, 0.0), "fallback")
        return GenerationResult(theme=theme, spec=None, trace=trace, timings=timings)


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _network_error(exc: Exception) -> str:
    """A short, non-leaky description of a transport failure."""
    return f"{type(exc).__name__}: {str(exc)[:200]}"
