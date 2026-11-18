import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from veracity_harness.agents import ChatCloudflare


@pytest.mark.parametrize("mixed", [False, True])
def test_cloudflare_keeps_malformed_history_as_unexecuted_text_without_invalid_wire_calls(mixed):
    malformed = '{"command": "curl'
    error_text = "Tool call could not be executed: arguments were malformed."
    valid = [{"name": "execute", "args": {"command": "date"}, "id": "valid-1"}] if mixed else []
    messages = [
        HumanMessage("Observe the case."),
        AIMessage(
            content="Original response.",
            tool_calls=valid,
            invalid_tool_calls=[
                {
                    "name": "execute",
                    "args": malformed,
                    "id": "broken-1",
                    "error": "invalid JSON",
                    "type": "invalid_tool_call",
                }
            ],
        ),
    ]
    if mixed:
        messages.append(ToolMessage(content="2026-11-01", tool_call_id="valid-1"))
    messages += [
        ToolMessage(content=error_text, tool_call_id="broken-1"),
        HumanMessage("Continue."),
    ]
    before = [m.model_dump() for m in messages]
    model = ChatCloudflare(model="fixture", api_key="fixture", base_url="http://unused")
    payload = model._get_request_payload(messages)
    for message in payload["messages"]:
        for call in message.get("tool_calls", []):
            json.loads(call["function"]["arguments"])
            assert call["id"] != "broken-1"
    assistant = payload["messages"][1]
    assert assistant["content"].startswith("Original response.")
    assert malformed in assistant["content"] or json.dumps(malformed) in assistant["content"]
    assert "broken-1" in assistant["content"] and "execute" in assistant["content"]
    assert error_text in assistant["content"]
    assert not any(m.get("tool_call_id") == "broken-1" for m in payload["messages"])
    if mixed:
        assert assistant["tool_calls"][0]["id"] == "valid-1"
        assert payload["messages"][2]["content"] == "2026-11-01"
        assert payload["messages"][2]["tool_call_id"] == "valid-1"
    assert [m.model_dump() for m in messages] == before


def test_cloudflare_valid_tool_history_payload_is_unchanged():
    model = ChatCloudflare(model="fixture", api_key="fixture", base_url="http://unused")
    messages = [
        HumanMessage("Observe."),
        AIMessage(
            content="Fetching.",
            tool_calls=[
                {
                    "name": "execute",
                    "args": {"command": "date"},
                    "id": "valid-1",
                }
            ],
        ),
        ToolMessage(content="2026-11-01", tool_call_id="valid-1"),
    ]
    assert model._get_request_payload(messages) == ChatOpenAI._get_request_payload(model, messages)
