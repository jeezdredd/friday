"""Агент + настоящий SDK Anthropic, HTTP подменён: проверяем потоковый разбор
серверного поиска, заполнитель, pause_turn, отключённый поиск и уплотнение истории."""

import json

import httpx2 as httpx  # SDK Anthropic работает поверх httpx2
import pytest
from anthropic import Anthropic

from friday import web_search
from friday.agent import Agent
from friday.config import settings
from friday.location import Location
from friday.tools import ToolRegistry


def sse(*events: dict) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events).encode()


def message(blocks: list[list[dict]], stop_reason: str) -> bytes:
    """blocks: для каждого блока список событий [start, *deltas]."""
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 1},
            },
        }
    ]
    for index, (start, *deltas) in enumerate(blocks):
        events.append({"type": "content_block_start", "index": index, "content_block": start})
        events += [{"type": "content_block_delta", "index": index, "delta": d} for d in deltas]
        events.append({"type": "content_block_stop", "index": index})
    events += [
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]
    return sse(*events)


SEARCH = [
    {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {}},
    {"type": "input_json_delta", "partial_json": '{"query": "курс доллара к тенге"}'},
]
RESULT = [
    {
        "type": "web_search_tool_result",
        "tool_use_id": "srvtoolu_1",
        "content": [
            {
                "type": "web_search_result",
                "url": "https://example.kz/rates",
                "title": "Курсы",
                "encrypted_content": "ENC",
                "page_age": "5 октября 2026",
            }
        ],
    }
]


def text(t: str) -> list[dict]:
    return [{"type": "text", "text": ""}, {"type": "text_delta", "text": t}]


class FakeAPI:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        status, body = self.responses.pop(0)
        if status != 200:
            return httpx.Response(status, json=body)
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(settings, "web_search", True)
    monkeypatch.setattr("friday.location.detect_by_ip", lambda: Location(43.2, 76.9, "Testcity", "Reg", "KZ", "UTC"))

    def make(*responses):
        api = FakeAPI(*responses)
        client = Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(api)), max_retries=0)
        started: list[str] = []
        agent = Agent(client=client, registry=ToolRegistry(), on_tool_start=started.append)
        return agent, api, started

    return make


def test_search_answer_filler_and_request_shape(setup):
    agent, api, started = setup((200, message([SEARCH, RESULT, text("Около пятисот "), text("тенге.")], "end_turn")))

    assert agent.ask("какой курс доллара?") == "Около пятисот тенге."
    assert started == ["web_search"]  # заполнитель узнаёт о поиске из потока

    tool = next(t for t in api.requests[0]["tools"] if t["name"] == "web_search")
    assert tool["type"] == settings.web_search_tool
    assert tool["allowed_callers"] == ["direct"]
    assert tool["user_location"] == {
        "type": "approximate",
        "timezone": "UTC",
        "city": "Testcity",
        "region": "Reg",
        "country": "KZ",
    }
    assert api.requests[0]["stream"] is True


def test_history_is_compacted_after_turn(setup):
    agent, _, _ = setup((200, message([SEARCH, RESULT, text("Около пятисот "), text("тенге.")], "end_turn")))
    agent.ask("какой курс доллара?")
    assert agent.history == [
        {"role": "user", "content": "какой курс доллара?"},
        {"role": "assistant", "content": [{"type": "text", "text": "Около пятисот тенге."}]},
    ]


def test_pause_turn_is_resumed(setup):
    agent, api, _ = setup(
        (200, message([SEARCH], "pause_turn")),
        (200, message([RESULT, text("Готово.")], "end_turn")),
    )
    assert agent.ask("новости") == "Готово."
    # второй запрос продолжает ход: последнее сообщение это незаконченный ход ассистента
    assert api.requests[1]["messages"][-1]["role"] == "assistant"
    assert api.requests[1]["messages"][-1]["content"][0]["type"] == "server_tool_use"


def test_disabled_search_falls_back(setup):
    error = {
        "type": "error",
        "error": {"type": "invalid_request_error", "message": "Web search is not enabled for this organization"},
    }
    agent, api, _ = setup((400, error), (200, message([text("Без поиска не скажу.")], "end_turn")))
    assert agent.ask("курс?") == "Без поиска не скажу."
    assert all(t["name"] != "web_search" for t in api.requests[1]["tools"])
    assert not agent._web_search_enabled


def test_search_can_be_turned_off(setup, monkeypatch):
    monkeypatch.setattr(settings, "web_search", False)
    assert web_search.tool_definition() is None


def test_compact_turn_keeps_client_tool_pairs():
    turn = [
        {"role": "user", "content": "включи свет и найди новости"},
        {
            "role": "assistant",
            "content": [
                {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {}},
                {"type": "web_search_tool_result", "tool_use_id": "s1", "content": []},
                {"type": "tool_use", "id": "t1", "name": "set_light", "input": {"on": True}},
            ],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Готово.", "citations": [{"url": "x"}]}]},
    ]
    out = web_search.compact_turn(turn)
    assert out[1]["content"] == [{"type": "tool_use", "id": "t1", "name": "set_light", "input": {"on": True}}]
    assert out[2] == turn[2]
    assert out[3]["content"] == [{"type": "text", "text": "Готово."}]


def test_unsupported_country_drops_country_and_keeps_search(setup):
    error = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "tools.13.web_search_20260318: Country code KZ is not supported.",
        },
    }
    agent, api, started = setup(
        (400, error), (200, message([SEARCH, RESULT, text("Около пятисот тенге.")], "end_turn"))
    )
    assert agent.ask("курс доллара?") == "Около пятисот тенге."
    assert agent._web_search_enabled
    location = next(t for t in api.requests[1]["tools"] if t["name"] == "web_search")["user_location"]
    assert "country" not in location and location["city"] == "Testcity"
    assert started == ["web_search"]


def test_location_mode_is_remembered_between_runs(setup):
    error = {
        "type": "error",
        "error": {"type": "invalid_request_error", "message": "web_search: Country code KZ is not supported."},
    }
    agent, _, _ = setup((400, error), (200, message([text("Ок.")], "end_turn")))
    agent.ask("тест")
    fresh, api, _ = setup((200, message([text("Ок.")], "end_turn")))
    fresh.ask("тест")
    assert len(api.requests) == 1  # сразу без страны, без лишнего запроса с ошибкой
    tool = next(t for t in api.requests[0]["tools"] if t["name"] == "web_search")
    assert "country" not in tool["user_location"]


def test_location_falls_back_to_none_if_still_rejected(setup):
    error = {
        "type": "error",
        "error": {"type": "invalid_request_error", "message": "web_search: user_location is not supported."},
    }
    agent, api, _ = setup((400, error), (400, error), (200, message([text("Ок.")], "end_turn")))
    assert agent.ask("тест") == "Ок."
    tool = next(t for t in api.requests[2]["tools"] if t["name"] == "web_search")
    assert "user_location" not in tool


def test_unrelated_bad_request_is_raised(setup):
    from anthropic import BadRequestError

    error = {"type": "error", "error": {"type": "invalid_request_error", "message": "messages: roles must alternate"}}
    agent, _, _ = setup((400, error))
    with pytest.raises(BadRequestError):
        agent.ask("тест")
    assert agent._web_search_enabled
