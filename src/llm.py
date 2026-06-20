"""Provider-agnostic LLM calls for triage and synthesis.

Selects the backend from `config.LLM_PROVIDER` ("anthropic" | "gemini"). Anthropic
is the default; set LLM_PROVIDER=gemini (with GEMINI_API_KEY) to run on Google's
free-tier Gemini Flash instead — far cheaper for the high-frequency triage pass,
while Anthropic gives the strongest daily-brief writing. Mix freely: the per-task
model ids live in config.py, so you can keep the brief on Anthropic and move only
triage to Gemini (or vice versa) just by setting LLM_PROVIDER.

Both backends expose the same two primitives, keyed by `task` ("triage"|"brief")
which selects the model:

  generate_json(task, system, user, schema) -> dict   forced JSON, schema-valid
  generate_text(task, system, user)         -> str    free-form prose

`schema` is a pydantic model class — the single source of truth. For Anthropic it
is rendered to a JSON-schema dict; for Gemini it is passed straight to the SDK.
The SDK imports are lazy so a deployment that only uses one provider needn't have
the other's package installed.
"""

from __future__ import annotations

import json
import time
from typing import Type

from pydantic import BaseModel

import config

# Per-provider, per-task model ids. Sourced from config so they're env-overridable.
_MODELS = {
    "anthropic": {
        "triage": config.ANTHROPIC_TRIAGE_MODEL,
        "brief": config.ANTHROPIC_BRIEF_MODEL,
    },
    "gemini": {
        "triage": config.GEMINI_TRIAGE_MODEL,
        "brief": config.GEMINI_BRIEF_MODEL,
    },
}


def _provider() -> str:
    p = config.LLM_PROVIDER
    if p not in _MODELS:
        raise ValueError(
            f"Unknown LLM_PROVIDER {p!r}; expected one of {sorted(_MODELS)}"
        )
    return p


# --- Anthropic backend ------------------------------------------------------

_anthropic_client = None


def _anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        _anthropic_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _anthropic_client


def _anthropic_schema(schema: Type[BaseModel]) -> dict:
    """Render a pydantic model to the strict JSON schema Anthropic expects."""
    s = schema.model_json_schema()
    s.pop("title", None)
    for prop in s.get("properties", {}).values():
        prop.pop("title", None)
    s["additionalProperties"] = False  # strict: no unspecified keys
    return s


def _anthropic_json(model, system, user, schema, max_tokens) -> dict:
    resp = _anthropic().messages.create(
        model=model,
        max_tokens=max_tokens,
        # Mark the stable system prefix cacheable; below Haiku's cache minimum today
        # but harmless, and it pays off if the watchlist context grows.
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": _anthropic_schema(schema)}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def _anthropic_text(model, system, user, max_tokens, effort) -> str:
    resp = _anthropic().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        output_config={"effort": effort},
        messages=[{"role": "user", "content": user}],
    )
    return next(b.text for b in resp.content if b.type == "text")


# --- Gemini backend ---------------------------------------------------------

_gemini_client = None


def _gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai

        # Reads GEMINI_API_KEY (or GOOGLE_API_KEY) from the environment.
        _gemini_client = genai.Client()
    return _gemini_client


def _gemini_generate(model, system, user, max_tokens, *, schema=None):
    """One Gemini call with retry on free-tier rate limits (429 / RESOURCE_EXHAUSTED).

    Thinking is disabled (budget 0): triage is a deterministic classification and
    the brief doesn't need it — this keeps latency down and avoids thinking tokens
    silently eating the max_output_tokens budget and truncating the response.
    """
    from google.genai import errors, types

    cfg = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    if schema is not None:
        cfg.response_mime_type = "application/json"
        cfg.response_schema = schema

    delay = 2.0
    for attempt in range(5):
        try:
            return _gemini().models.generate_content(model=model, contents=user, config=cfg)
        except errors.APIError as e:
            transient = getattr(e, "code", None) == 429
            if transient and attempt < 4:
                time.sleep(delay)
                delay *= 2
                continue
            raise


# --- public API -------------------------------------------------------------


def generate_json(task: str, system: str, user: str, *, schema: Type[BaseModel], max_tokens: int = 512) -> dict:
    """Return a parsed, schema-valid JSON object for `task` from the active provider."""
    provider = _provider()
    model = _MODELS[provider][task]
    if provider == "anthropic":
        return _anthropic_json(model, system, user, schema, max_tokens)
    resp = _gemini_generate(model, system, user, max_tokens, schema=schema)
    return json.loads(resp.text)


def generate_text(task: str, system: str, user: str, *, max_tokens: int = 8000, effort: str = "medium") -> str:
    """Return free-form text for `task` from the active provider. `effort` applies
    to Anthropic only (Gemini thinking is disabled); it is ignored for Gemini."""
    provider = _provider()
    model = _MODELS[provider][task]
    if provider == "anthropic":
        return _anthropic_text(model, system, user, max_tokens, effort)
    resp = _gemini_generate(model, system, user, max_tokens)
    return resp.text
