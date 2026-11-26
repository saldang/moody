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


def test_guard_model_needs_ollama_endpoint(monkeypatch, pki_dir, tmp_path):
    from moody.brain.__main__ import build_agent
    svc = pki_dir / "services" / "gateway"
    for k, v in {"MOODY_TLS_CERT": svc / "tls.pem", "MOODY_TLS_KEY": svc / "tls.key",
                 "MOODY_TLS_CA": pki_dir / "service-ca" / "ca.pem", "MOODY_DATA_DIR": tmp_path,
                 "MOODY_TOOL_POLICY": "../deploy/config/tool-policy.yaml",
                 "MOODY_GUARD_MODEL": "granite3-guardian:2b"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.delenv("MOODY_GUARD_URL", raising=False)
    monkeypatch.setenv("MOODY_LLM_BACKEND", "openai")      # QVAC: no Ollama API -> disabled
    assert build_agent().guard is None
    monkeypatch.setenv("MOODY_GUARD_URL", "http://ollama:11434")
    assert build_agent().guard is not None
    monkeypatch.delenv("MOODY_GUARD_URL")
    monkeypatch.setenv("MOODY_LLM_BACKEND", "ollama")      # classic stack: same Ollama endpoint
    assert build_agent().guard is not None
