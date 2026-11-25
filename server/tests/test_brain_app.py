from fastapi.testclient import TestClient

from moody.brain.agent import TurnResult
from moody.brain.app import create_app


class FakeTools:
    async def call(self, name, args, *, subject, system=False):
        assert system and name == "wellbeing.due_reminders"
        return '{"due": ["bere acqua"]}'


class FakeAgent:
    tools = FakeTools()

    async def turn(self, subject, session_id, text):
        return TurnResult(f"eco {subject}")


def test_turn_and_notifications():
    client = TestClient(create_app(FakeAgent()))
    r = client.post("/v1/turn", json={"subject": "res-001", "session_id": "abc", "text": "ciao"})
    assert r.status_code == 200 and r.json()["reply"] == "eco res-001"
    assert client.get("/v1/notifications", params={"subject": "res-001"}).json() == {"items": ["Promemoria: bere acqua"]}


def test_input_validation():
    client = TestClient(create_app(FakeAgent()))
    assert client.post("/v1/turn", json={"subject": "../etc", "session_id": "a", "text": "x"}).status_code == 422
    assert client.post("/v1/turn", json={"subject": "r", "session_id": "a", "text": "x" * 5000}).status_code == 422
    assert client.get("/docs").status_code == 404  # no public API docs in production


def test_env_empty_means_default(monkeypatch):
    from moody.common.config import env
    monkeypatch.setenv("MOODY_X", "")
    assert env("MOODY_X", "fallback") == "fallback"
    monkeypatch.setenv("MOODY_X", "set")
    assert env("MOODY_X", "fallback") == "set"
