from dataclasses import dataclass, field
from typing import Any

from friday.agent import Agent
from friday.tools import ToolRegistry


@dataclass
class Block:
    data: dict[str, Any]

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        return dict(self.data)


@dataclass
class Response:
    content: list[Block]
    stop_reason: str


@dataclass
class FakeClient:
    responses: list[Response]
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def make_registry():
    reg = ToolRegistry()
    state = {}

    def set_light(on: bool) -> str:
        """Свет."""
        state["on"] = on
        return "ok"

    reg.register(set_light)
    return reg, state


def test_tool_call_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("friday.tools.memory.settings", type("S", (), {"data_dir": tmp_path})())
    reg, state = make_registry()
    client = FakeClient(
        [
            Response(
                [Block({"type": "tool_use", "id": "t1", "name": "set_light", "input": {"on": True}})],
                "tool_use",
            ),
            Response([Block({"type": "text", "text": "Свет включён."})], "end_turn"),
        ]
    )
    agent = Agent(client=client, registry=reg)

    assert agent.ask("включи свет") == "Свет включён."
    assert state["on"] is True
    tool_result = agent.history[2]["content"][0]
    assert tool_result["tool_use_id"] == "t1" and tool_result["is_error"] is False
    assert client.calls[0]["tools"][0]["name"] == "set_light"


def test_history_trim_keeps_tool_pairs(monkeypatch):
    reg, _ = make_registry()
    agent = Agent(client=FakeClient([]), registry=reg)
    monkeypatch.setattr("friday.agent.settings", type("S", (), {"max_history": 3})())
    agent.history = [
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": [{"type": "tool_use"}]},
        {"role": "user", "content": [{"type": "tool_result"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "a"}]},
        {"role": "user", "content": "2"},
        {"role": "assistant", "content": [{"type": "text", "text": "b"}]},
    ]
    agent._trim_history()
    assert agent.history[0] == {"role": "user", "content": "2"}
