"""One small function that asks a language model a question, over plain HTTPS, for three providers.

    complete("anthropic" | "openai" | "google", model, system, user, api_key=...)

No SDKs, no tool-calling formats: the model only ever returns TEXT. It can never place an
order; at most it writes a proposed-trade line that the bot turns into an unconfirmed ticket.
API keys are passed in by the caller (read from environment variables on the machine that runs
the bot) and are never logged or included in error messages.
"""
from __future__ import annotations

import httpx

PROVIDERS = ("anthropic", "openai", "google")
DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5"}   # openai/google: you must name a model you have access to
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "google": "GOOGLE_API_KEY"}
MAX_OUTPUT_TOKENS = 700


class LLMError(RuntimeError):
    pass


def _request(provider: str, model: str, system: str, user: str, key: str) -> tuple[str, dict, dict]:
    if provider == "anthropic":
        return ("https://api.anthropic.com/v1/messages",
                {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                {"model": model, "max_tokens": MAX_OUTPUT_TOKENS, "system": system,
                 "messages": [{"role": "user", "content": user}]})
    if provider == "openai":
        return ("https://api.openai.com/v1/chat/completions",
                {"authorization": f"Bearer {key}", "content-type": "application/json"},
                {"model": model, "max_completion_tokens": MAX_OUTPUT_TOKENS,
                 "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    if provider == "google":
        return (f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                {"x-goog-api-key": key, "content-type": "application/json"},
                {"systemInstruction": {"parts": [{"text": system}]},
                 "contents": [{"role": "user", "parts": [{"text": user}]}],
                 "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS}})
    raise LLMError(f"Unknown provider {provider!r}; use one of {PROVIDERS}.")


def _text(provider: str, data: dict) -> str:
    try:
        if provider == "anthropic":
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text").strip()
        if provider == "openai":
            return (data["choices"][0]["message"]["content"] or "").strip()
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"{provider} returned a reply this code could not read.") from exc


def complete(provider: str, model: str, system: str, user: str, *, api_key: str,
             timeout: float = 60.0, client: httpx.Client | None = None) -> str:
    if provider not in PROVIDERS:
        raise LLMError(f"Unknown provider {provider!r}; use one of {PROVIDERS}.")
    if not api_key:
        raise LLMError(f"No API key: set {KEY_ENV[provider]} on the machine running the bot.")
    if not model:
        raise LLMError(f"Set MT5_AI_LLM_MODEL to a {provider} model your key can use.")
    url, headers, body = _request(provider, model, system, user, api_key)
    own = client is None
    client = client or httpx.Client(timeout=timeout)
    try:
        r = client.post(url, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach {provider}: {type(exc).__name__}.") from None
    finally:
        if own:
            client.close()
    if r.status_code != 200:
        raise LLMError(f"{provider} refused the request (HTTP {r.status_code}). Check the key, model name and billing.")
    return _text(provider, r.json())
