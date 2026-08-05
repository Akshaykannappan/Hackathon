"""Mesh API Client.

The ONLY module in the repository permitted to import `openai` and communicate
with the Mesh API for chat completions and vector embeddings.
"""

import json
import httpx
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings


class MeshUnavailableError(Exception):
    """Raised when Mesh API is unreachable or fails after retries."""

    pass


def _get_setting(key: str, default: str | None = None) -> str | None:
    """Helper to read setting dynamically, supporting case variations."""
    if hasattr(settings, key):
        return getattr(settings, key)
    if hasattr(settings, key.lower()):
        return getattr(settings, key.lower())
    if hasattr(settings, key.upper()):
        return getattr(settings, key.upper())
    return default


def _strip_code_fences(text: str) -> str:
    """Drop a leading ```/```json fence and its closing counterpart."""
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_object(text: str) -> str:
    """Return the outermost ``{...}`` span, or the input when there is none.

    Weak models bracket their JSON with conversational text — "Sure, here's the
    recommendation:" before it, "Let me know if..." after. Slicing from the
    first `{` to the last `}` discards both without needing to understand them.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return text
    return text[start : end + 1]


_STRUCTURAL_AFTER_STRING = frozenset(',:}]')


def _escape_inner_quotes(text: str) -> str:
    """Escape double quotes that appear *inside* a JSON string value.

    A model writing `"the design in "Course Title" is..."` emits a value whose
    quotes were never escaped. Walking the text, a `"` seen inside a string only
    closes it when the next non-whitespace character is structural (`,`/`:`/`}`/
    `]`) or the input ends; anything else means the model was quoting, so the
    character is escaped instead.
    """
    out: list[str] = []
    in_string = False
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        if not in_string:
            out.append(char)
            if char == '"':
                in_string = True
            index += 1
            continue

        if char == "\\" and index + 1 < length:
            out.append(text[index : index + 2])
            index += 2
            continue

        if char == '"':
            lookahead = index + 1
            while lookahead < length and text[lookahead].isspace():
                lookahead += 1
            if lookahead >= length or text[lookahead] in _STRUCTURAL_AFTER_STRING:
                out.append(char)
                in_string = False
            else:
                out.append('\\"')
            index += 1
            continue

        out.append(char)
        index += 1

    return "".join(out)


def _traceable_llm(name: str):
    """Lazy decorator for langsmith's @traceable, gracefully no-oping if absent or disabled."""
    def decorator(fn):
        if _get_setting("langsmith_tracing", False) and _get_setting("langsmith_api_key", None):
            try:
                from langsmith import traceable

                return traceable(name=name, run_type="llm")(fn)
            except Exception:
                pass
        return fn

    return decorator


class MeshClient:
    """Centralized Mesh API client."""

    def __init__(self):
        base_url = _get_setting("mesh_base_url", "https://api.meshapi.ai/v1") or "https://api.meshapi.ai/v1"
        api_key = _get_setting("mesh_api_key", "") or ""
        # This module builds its client at import time, and `OpenAI(api_key="")`
        # raises rather than deferring. Without the placeholder, importing
        # anything downstream of Mesh — the agent, and therefore most of the
        # test suite — fails outright when MESH_API_KEY is unset, which is the
        # normal state of a fresh clone and of CI before the secret is wired.
        # A real key still overrides this on every call via `_sync_api_key`;
        # the placeholder only ever reaches the wire as a 401, which the
        # retry/`MeshUnavailableError` path already handles.
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key or "missing-mesh-api-key",
        )

    def _sync_api_key(self):
        """Ensure client uses latest API key from settings."""
        current_key = _get_setting("mesh_api_key", "") or ""
        if current_key and self.client.api_key != current_key:
            self.client.api_key = current_key

    @_traceable_llm("Mesh LLM Chat")
    def chat(self, messages: list[dict], **kwargs) -> str:
        """Send chat completion request to Mesh API with retries."""
        model = kwargs.pop("model", None) or _get_setting("mesh_chat_model", "openai/gpt-4o-mini")

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=4),
            reraise=True,
        )
        def _call():
            self._sync_api_key()
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs,
            )
            return response.choices[0].message.content or ""

        try:
            return _call()
        except Exception as e:
            raise MeshUnavailableError(f"Mesh chat call failed after 3 attempts: {e}") from e

    @_traceable_llm("Mesh LLM Chat JSON")
    def chat_json(self, messages: list[dict], **kwargs) -> dict:
        """Send chat completion request expecting JSON object response.

        Free-tier models do not reliably honour "return only JSON". Three
        recoveries are applied in order, each strictly wider than the last:

        1. markdown fences are stripped
        2. the outermost ``{...}`` block is extracted, so conversational
           preamble before it and commentary after it are discarded
        3. failing that, unescaped double quotes *inside* string values are
           escaped — the model quoting a course title mid-sentence produces
           JSON that is otherwise structurally sound

        Step 3 runs only after a parse has already failed, so well-formed
        output is never rewritten.
        """
        content = self.chat(messages, **kwargs)
        cleaned = _strip_code_fences(content.strip())
        block = _extract_json_object(cleaned)

        for candidate in (block, _escape_inner_quotes(block)):
            try:
                data = json.loads(candidate)
            except json.JSONDecodeError as err:
                last_error: Exception = err
                continue
            if not isinstance(data, dict):
                raise ValueError(
                    f"Expected JSON object (dict), got {type(data).__name__}"
                )
            return data

        raise ValueError(
            f"Invalid JSON returned by Mesh chat: {last_error}\nRaw content:\n{content}"
        ) from last_error

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Send batched embedding request to Mesh API in a single call."""
        if not texts:
            return []

        embedding_model = model or _get_setting("mesh_embedding_model", "openai/text-embedding-3-small")

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=4),
            reraise=True,
        )
        def _call():
            self._sync_api_key()
            response = self.client.embeddings.create(
                input=texts,
                model=embedding_model,
            )
            # Ensure returning vectors in original input order
            sorted_data = sorted(response.data, key=lambda d: d.index)
            return [d.embedding for d in sorted_data]

        try:
            return _call()
        except Exception as e:
            raise MeshUnavailableError(f"Mesh embed call failed after 3 attempts: {e}") from e

    def list_embedding_models(self) -> list[dict]:
        """Fetch available models from Mesh API and filter for embedding models."""
        base_url = (_get_setting("mesh_base_url", "https://api.meshapi.ai/v1") or "").rstrip("/")
        if base_url.endswith("/v1"):
            url = f"{base_url}/models"
        else:
            url = f"{base_url}/v1/models"

        api_key = _get_setting("mesh_api_key", "") or ""
        auth_header = f"Bearer {api_key}" if not api_key.startswith("Bearer ") else api_key
        headers = {"Authorization": auth_header}

        try:
            response = httpx.get(url, headers=headers, timeout=15.0)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            raise MeshUnavailableError(f"Failed to fetch models from Mesh API ({url}): {e}") from e

        if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
            models_list = data["data"]
        elif isinstance(data, list):
            models_list = data
        else:
            models_list = []

        return [
            m for m in models_list
            if isinstance(m, dict) and m.get("supports_embeddings") is True
        ]


# Module-level instance export
mesh_client = MeshClient()

__all__ = ["MeshClient", "MeshUnavailableError", "mesh_client"]
