"""LLM client abstraction for PawPal AI.

The workflow never talks to a provider SDK directly - it depends on the tiny
`LLMClient` protocol below. Four implementations exist:

* `GeminiLLMClient` - Google Gemini adapter over the REST API (stdlib only).
* `AnthropicLLMClient` - Anthropic adapter (lazy-imports `anthropic`).
* `FakeLLMClient` (this module) - returns scripted responses for tests.
* `DemoLLMClient` (`pawpal_ai.demo_client`) - deterministic rule-based
  extractor so graders can run the full system without an API key.

The live provider is selected with PAWPAL_LLM_PROVIDER (gemini | anthropic).
Configuration comes from environment variables (see `.env.example`); a
minimal `.env` loader is included so no extra dependency is needed.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

try:  # Protocol lives in typing on Python 3.8+
    from typing import Protocol
except ImportError:  # pragma: no cover
    Protocol = object  # type: ignore

DEFAULT_MODEL = "claude-opus-5"


# ------------------------------------------------------------------ errors

class LLMClientError(Exception):
    """Base class for every LLM client failure."""


class MissingAPIKeyError(LLMClientError):
    """No API key configured for live-model mode."""


class NetworkError(LLMClientError):
    """The provider could not be reached."""


class RateLimitError(LLMClientError):
    """The provider rate-limited the request."""


class InvalidResponseError(LLMClientError):
    """The provider responded, but not with parseable JSON."""


class ProviderError(LLMClientError):
    """The provider returned an error response."""


# ---------------------------------------------------------------- protocol

class LLMClient(Protocol):
    """Anything that can turn prompts into a structured (dict) response."""

    def generate_structured(self, system_prompt: str, user_prompt: str) -> dict:
        """Return the model's response parsed as a JSON object (dict)."""
        ...


# ------------------------------------------------------------ JSON parsing

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json_object(text: str) -> dict:
    """Parse a JSON object out of model text output.

    Strict JSON is expected; as an intentional, documented normalization
    layer, a single markdown-fenced JSON block is also accepted (models
    occasionally wrap output despite instructions). Anything else raises
    InvalidResponseError.
    """
    candidate = text.strip()
    fenced = _FENCE_RE.search(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as err:
        raise InvalidResponseError(f"Model did not return valid JSON: {err}") from err
    if not isinstance(data, dict):
        raise InvalidResponseError(
            f"Model returned JSON of type {type(data).__name__}, expected an object"
        )
    return data


# --------------------------------------------------------------- fake client

class FakeLLMClient:
    """Deterministic scripted client for unit tests.

    Yields each queued item in order: dicts are returned as responses,
    exceptions are raised. The last item repeats if calls exceed the queue.
    """

    def __init__(self, responses: list):
        if not responses:
            raise ValueError("FakeLLMClient needs at least one scripted response")
        self.responses = list(responses)
        self.calls: list = []  # (system_prompt, user_prompt) per call

    def generate_structured(self, system_prompt: str, user_prompt: str) -> dict:
        """Return (or raise) the next scripted item."""
        self.calls.append((system_prompt, user_prompt))
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        item = self.responses[index]
        if isinstance(item, Exception):
            raise item
        return item


# ------------------------------------------------------------- live client

class AnthropicLLMClient:
    """Real provider adapter using the official `anthropic` SDK."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Create the client; raises MissingAPIKeyError without a key."""
        self.api_key = api_key or os.environ.get("PAWPAL_API_KEY") \
            or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise MissingAPIKeyError(
                "No API key found. Set PAWPAL_API_KEY (or ANTHROPIC_API_KEY) in "
                "your environment or .env file to use the live model."
            )
        self.model = model or os.environ.get("PAWPAL_LLM_MODEL", DEFAULT_MODEL)

    def generate_structured(self, system_prompt: str, user_prompt: str) -> dict:
        """Call the model once and parse its reply as a JSON object."""
        try:
            import anthropic
        except ImportError as err:  # pragma: no cover - depends on install
            raise ProviderError(
                "The 'anthropic' package is not installed. "
                "Run: pip install -r requirements.txt"
            ) from err

        client = anthropic.Anthropic(api_key=self.api_key)
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.AuthenticationError as err:
            raise MissingAPIKeyError(f"API key was rejected: {err}") from err
        except anthropic.RateLimitError as err:
            raise RateLimitError(f"Rate limited by provider: {err}") from err
        except anthropic.APIConnectionError as err:
            raise NetworkError(f"Could not reach the provider: {err}") from err
        except anthropic.APIStatusError as err:
            raise ProviderError(f"Provider error ({err.status_code}): {err.message}") from err

        if getattr(response, "stop_reason", None) == "refusal":
            raise ProviderError("The model declined to answer this request.")
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        if not text.strip():
            raise InvalidResponseError("Model returned an empty response")
        return extract_json_object(text)


# ------------------------------------------------------- Gemini live client

GEMINI_DEFAULT_MODEL = "gemini-3.5-flash"
_GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


class GeminiLLMClient:
    """Google Gemini adapter using the REST API (stdlib only, no SDK).

    Sends the system prompt as `systemInstruction`, requests
    `application/json` output, and parses the reply into a dict.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 timeout: float = 60.0):
        """Create the client; raises MissingAPIKeyError without a key."""
        self.api_key = api_key or os.environ.get("PAWPAL_API_KEY") \
            or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise MissingAPIKeyError(
                "No API key found. Set PAWPAL_API_KEY (or GEMINI_API_KEY) in "
                "your environment or .env file to use the live model."
            )
        self.model = model or os.environ.get("PAWPAL_LLM_MODEL", GEMINI_DEFAULT_MODEL)
        self.timeout = timeout

    def generate_structured(self, system_prompt: str, user_prompt: str) -> dict:
        """Call Gemini once and parse its reply as a JSON object."""
        import urllib.error
        import urllib.request

        payload = json.dumps({
            # Gemini's REST API follows the Google JSON convention: protobuf
            # field names are lower camel case (rather than Python SDK names).
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0,
            },
        }).encode("utf-8")
        request = urllib.request.Request(
            _GEMINI_ENDPOINT.format(model=self.model),
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            detail = ""
            try:
                detail = json.loads(err.read().decode("utf-8"))["error"]["message"]
            except Exception:
                pass
            if err.code in (401, 403):
                raise MissingAPIKeyError(
                    f"API key was rejected ({err.code}): {detail}") from err
            if err.code == 429:
                raise RateLimitError(f"Rate limited by provider: {detail}") from err
            raise ProviderError(f"Provider error ({err.code}): {detail}") from err
        except urllib.error.URLError as err:
            raise NetworkError(f"Could not reach the provider: {err.reason}") from err

        try:
            parts = body["candidates"][0]["content"]["parts"]
            # Thinking-capable Gemini models may return internal reasoning as
            # a separate part before the final response.  It is not part of
            # the requested JSON contract and must not be concatenated with
            # the final answer.
            text = "".join(
                part.get("text", "") for part in parts
                if not part.get("thought", False)
            )
        except (KeyError, IndexError, TypeError) as err:
            reason = body.get("candidates", [{}])[0].get("finishReason", "unknown") \
                if isinstance(body.get("candidates"), list) and body["candidates"] \
                else body.get("promptFeedback", {}).get("blockReason", "unknown")
            raise InvalidResponseError(
                f"Model returned no text (reason: {reason})") from err
        if not text.strip():
            raise InvalidResponseError("Model returned an empty response")
        return extract_json_object(text)


# ------------------------------------------------------------ configuration

def load_env_file(path: Optional[Path] = None) -> None:
    """Load simple KEY=VALUE lines from a .env file into os.environ.

    Existing environment variables win; missing files are ignored. This keeps
    the project dependency-free instead of adding python-dotenv.
    """
    env_path = path or Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def live_mode_enabled() -> bool:
    """True when PAWPAL_USE_LIVE_MODEL is set to a truthy value."""
    return os.environ.get("PAWPAL_USE_LIVE_MODEL", "false").lower() in {
        "1", "true", "yes", "on",
    }


def create_live_client() -> LLMClient:
    """Build the live client selected by PAWPAL_LLM_PROVIDER (default gemini)."""
    provider = os.environ.get("PAWPAL_LLM_PROVIDER", "gemini").strip().lower()
    if provider == "anthropic":
        return AnthropicLLMClient()
    if provider == "gemini":
        return GeminiLLMClient()
    raise ProviderError(
        f"Unknown PAWPAL_LLM_PROVIDER {provider!r} (expected gemini or anthropic)"
    )


def create_client_from_env():
    """Build the configured client: live provider adapter or offline demo.

    Returns (client, mode) where mode is "live" or "demo". Falls back to the
    deterministic demo client whenever live mode is off or misconfigured, so
    the application always stays usable.
    """
    from .demo_client import DemoLLMClient  # local import avoids a cycle

    load_env_file()
    if live_mode_enabled():
        return create_live_client(), "live"
    return DemoLLMClient(), "demo"
