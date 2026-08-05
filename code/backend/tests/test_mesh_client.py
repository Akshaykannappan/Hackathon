"""Tests for `chat_json` parsing resilience.

The chat model in use is a free-tier one (`minimax/m2-her`, see
`docs/phases/phase-01-foundation.md`). It ignores "return only JSON" in three
recurring ways, all observed in real `agent_runs` rows. None of these tests
touch the network: `chat` is replaced, so only the parsing is under test.
"""

import json

import pytest

from app.ai.mesh_client import MeshClient


@pytest.fixture(name="client")
def client_fixture(monkeypatch: pytest.MonkeyPatch) -> MeshClient:
    """A MeshClient whose `chat` returns whatever the test sets on it."""
    client = MeshClient()

    def _reply(payload: str) -> None:
        monkeypatch.setattr(
            MeshClient, "chat", lambda self, messages, **kwargs: payload
        )

    client.reply = _reply  # type: ignore[attr-defined]
    return client


def test_plain_json_is_parsed(client: MeshClient):
    client.reply('{"queries": ["agentic ai", "rag"]}')
    assert client.chat_json([]) == {"queries": ["agentic ai", "rag"]}


def test_markdown_fences_are_stripped(client: MeshClient):
    client.reply('```json\n{"message": "hi", "products": [1, 2]}\n```')
    assert client.chat_json([])["products"] == [1, 2]


def test_preamble_and_trailing_text_are_discarded(client: MeshClient):
    """Text before AND after the JSON object. The outermost {...} is extracted."""
    client.reply(
        "Sure! Here is the recommendation you asked for:\n\n"
        '{"message": "Three courses that build on your Airflow work.", '
        '"products": [21, 16, 17], "reasoning": "Continues the ETL thread."}\n\n'
        "Let me know if you would like me to adjust the tone or pick different "
        "courses instead."
    )

    payload = client.chat_json([])

    assert payload["products"] == [21, 16, 17]
    assert payload["reasoning"] == "Continues the ETL thread."
    assert payload["message"].startswith("Three courses")


def test_preamble_and_trailing_text_around_fenced_json(client: MeshClient):
    """Both recoveries at once: chatty wrapper plus a code fence."""
    client.reply(
        "Here you go:\n```json\n"
        '{"queries": ["langgraph agents", "rag evaluation"]}\n'
        "```\nHope that helps!"
    )
    assert client.chat_json([])["queries"] == ["langgraph agents", "rag evaluation"]


def test_unescaped_quotes_inside_a_string_value_are_repaired(client: MeshClient):
    """The exact payload that degraded agent run #20 — course titles quoted mid-sentence."""
    client.reply(
        '{"message": "Since you spent two minutes reading about building agentic '
        'systems with LangGraph, the stateful agent design in "Building Agentic AI '
        'Systems with LangGraph" (ID: 1) is the perfect next step. You might also '
        'benefit from "Multi-Agent Orchestration Patterns" (ID: 2).", '
        '"products": [1, 2], "reasoning": "Both match the agentic AI signal."}'
    )

    payload = client.chat_json([])

    assert payload["products"] == [1, 2]
    assert "Building Agentic AI Systems with LangGraph" in payload["message"]
    assert payload["reasoning"] == "Both match the agentic AI signal."


def test_escaped_quotes_in_valid_json_are_left_alone(client: MeshClient):
    """The repair must not fire on output that already parses."""
    original = {
        "message": 'You looked at "Intro to AI Agents" twice.',
        "products": [6],
    }
    client.reply(json.dumps(original))
    assert client.chat_json([]) == original


def test_a_json_array_is_rejected(client: MeshClient):
    """The contract is an object. A bare array is a contract violation, not JSON to fix."""
    client.reply("[1, 2, 3]")
    with pytest.raises(ValueError, match="Expected JSON object"):
        client.chat_json([])


def test_unrecoverable_output_raises_with_the_raw_content(client: MeshClient):
    client.reply("I'm sorry, I can't help with that request.")
    with pytest.raises(ValueError, match="Invalid JSON returned by Mesh chat"):
        client.chat_json([])
