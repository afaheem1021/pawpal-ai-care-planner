"""Tests for the LLM client layer (offline - HTTP is mocked)."""

import io
import json
import os
import sys
import urllib.error
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pawpal_ai.llm_client import (
    FakeLLMClient,
    GeminiLLMClient,
    InvalidResponseError,
    MissingAPIKeyError,
    ProviderError,
    RateLimitError,
    create_live_client,
    extract_json_object,
)


# ------------------------------------------------------------ json parsing

def test_extract_json_object_strict_and_fenced():
    assert extract_json_object('{"a": 1}') == {"a": 1}
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_object_rejects_garbage():
    with pytest.raises(InvalidResponseError):
        extract_json_object("not json at all")
    with pytest.raises(InvalidResponseError):
        extract_json_object("[1, 2, 3]")  # list, not object


# ------------------------------------------------------------- fake client

def test_fake_client_replays_and_repeats():
    client = FakeLLMClient([{"a": 1}, {"b": 2}])
    assert client.generate_structured("s", "u") == {"a": 1}
    assert client.generate_structured("s", "u") == {"b": 2}
    assert client.generate_structured("s", "u") == {"b": 2}  # last repeats
    assert len(client.calls) == 3


# ----------------------------------------------------------- gemini client

def gemini_response(text):
    body = json.dumps({
        "candidates": [{"content": {"parts": [{"text": text}]},
                        "finishReason": "STOP"}]
    }).encode()
    response = mock.MagicMock()
    response.read.return_value = body
    response.__enter__ = lambda self: self
    response.__exit__ = lambda self, *args: False
    return response


def make_client():
    return GeminiLLMClient(api_key="test-key-not-real", model="gemini-test")


def test_gemini_requires_api_key(monkeypatch):
    monkeypatch.delenv("PAWPAL_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(MissingAPIKeyError):
        GeminiLLMClient()


def test_gemini_parses_json_reply():
    with mock.patch("urllib.request.urlopen",
                    return_value=gemini_response('{"tasks": []}')) as opened:
        result = make_client().generate_structured("system", "user")
    assert result == {"tasks": []}
    request = opened.call_args[0][0]
    sent = json.loads(request.data.decode())
    assert sent["systemInstruction"]["parts"][0]["text"] == "system"
    assert sent["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_ignores_thinking_parts():
    body = json.dumps({
        "candidates": [{"content": {"parts": [
            {"thought": True, "text": "internal reasoning"},
            {"text": '{"tasks": []}'},
        ]}}]
    }).encode()
    response = mock.MagicMock()
    response.read.return_value = body
    response.__enter__ = lambda self: self
    response.__exit__ = lambda self, *args: False
    with mock.patch("urllib.request.urlopen", return_value=response):
        assert make_client().generate_structured("s", "u") == {"tasks": []}


def test_live_client_dispatches_to_gemini_by_default(monkeypatch):
    monkeypatch.setenv("PAWPAL_API_KEY", "test-key-not-real")
    monkeypatch.delenv("PAWPAL_LLM_PROVIDER", raising=False)
    assert isinstance(create_live_client(), GeminiLLMClient)


def test_live_client_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("PAWPAL_LLM_PROVIDER", "unknown-provider")
    with pytest.raises(ProviderError, match="Unknown PAWPAL_LLM_PROVIDER"):
        create_live_client()


def test_gemini_maps_http_errors():
    def http_error(code):
        return urllib.error.HTTPError(
            "url", code, "err", {}, io.BytesIO(
                json.dumps({"error": {"message": "boom"}}).encode())
        )

    with mock.patch("urllib.request.urlopen", side_effect=http_error(429)):
        with pytest.raises(RateLimitError):
            make_client().generate_structured("s", "u")
    with mock.patch("urllib.request.urlopen", side_effect=http_error(403)):
        with pytest.raises(MissingAPIKeyError):
            make_client().generate_structured("s", "u")
    with mock.patch("urllib.request.urlopen", side_effect=http_error(500)):
        with pytest.raises(ProviderError):
            make_client().generate_structured("s", "u")


def test_gemini_rejects_empty_candidates():
    body = json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}).encode()
    response = mock.MagicMock()
    response.read.return_value = body
    response.__enter__ = lambda self: self
    response.__exit__ = lambda self, *args: False
    with mock.patch("urllib.request.urlopen", return_value=response):
        with pytest.raises(InvalidResponseError, match="SAFETY"):
            make_client().generate_structured("s", "u")
