import json

import pytest

from moody.brain.agent import Agent, AgentSettings
from moody.brain.guardrails import CRISIS_REPLY
from moody.brain.llm import ChatResult, ToolCall
from moody.brain.rag import KnowledgeBase, chunk_markdown, format_passages
from moody.brain.tools import ToolPolicy, ToolRegistry, ToolSpec, _strip_injected


class FakeProvider:
    name = "wellbeing"

    def __init__(self):
        self.calls = []

    async def list_tools(self):
        schema = {"type": "object", "properties": {"subject": {"type": "string"}, "score": {"type": "integer"}},
                  "required": ["subject", "score"]}
        params, injected = _strip_injected(schema)
        return [ToolSpec(f"wellbeing.{n}", n, params, injected)
                for n in ("mood_checkin", "erase_my_data", "request_help", "due_reminders", "secret_tool")]

    async def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        return json.dumps({"ok": True})


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.seen_tools = None
        self.seen_messages = None

    async def chat(self, messages, tools=None):
        self.seen_tools = tools
        self.seen_messages = messages
        return self.script.pop(0)

    def assistant_message(self, result):
        return {"role": "assistant", "content": result.content}

    def tool_message(self, call, content):
        return {"role": "tool", "content": content}


POLICY = ToolPolicy(
    tools={"wellbeing.mood_checkin": "allow", "wellbeing.erase_my_data": "confirm",
           "wellbeing.request_help": "allow", "wellbeing.due_reminders": "allow"},
    deny_patterns=["*lock*"], internal_only=["wellbeing.due_reminders"],
)


async def make_agent(script, escalation="ask"):
    provider = FakeProvider()
    registry = ToolRegistry([provider], POLICY)
    await registry.refresh(force=True)
    llm = FakeLLM(script)
    return Agent(llm, registry, None, AgentSettings(escalation=escalation)), llm, provider


def test_policy_decisions():
    assert POLICY.decide("wellbeing.mood_checkin") == "allow"
    assert POLICY.decide("homeassistant.HassUnlock") == "deny"
    assert POLICY.decide("homeassistant.front_door_lock") == "deny"
    assert POLICY.decide("wellbeing.due_reminders") == "deny"  # internal only
    assert POLICY.decide("wellbeing.unknown") == "deny"  # deny by default


async def test_llm_never_sees_subject_and_cannot_spoof_it():
    agent, llm, provider = await make_agent([
        ChatResult("", [ToolCall("wellbeing__mood_checkin", {"score": 4, "subject": "res-999"})]),
        ChatResult("Grazie, ho annotato che ti senti bene."),
    ])
    out = await agent.turn("res-001", "s1", "Oggi mi sento bene, direi un quattro")
    assert "annotato" in out.reply
    exposed = {t["function"]["name"] for t in llm.seen_tools}
    assert exposed == {"wellbeing__mood_checkin", "wellbeing__erase_my_data", "wellbeing__request_help"}
    for tool in llm.seen_tools:
        assert "subject" not in tool["function"]["parameters"]["properties"]
    assert provider.calls == [("mood_checkin", {"score": 4, "subject": "res-001"})]


async def test_sensitive_tool_requires_confirmation():
    agent, _, provider = await make_agent([ChatResult("", [ToolCall("wellbeing__erase_my_data", {})])])
    out = await agent.turn("res-001", "s1", "Cancella tutti i miei dati")
    assert out.category == "confirm" and provider.calls == []
    out = await agent.turn("res-001", "s1", "sì, confermo")
    assert provider.calls == [("erase_my_data", {"subject": "res-001"})]
    assert "cancellato" in out.reply


async def test_crisis_offer_then_escalate_on_yes():
    agent, llm, provider = await make_agent([])
    out = await agent.turn("res-001", "s1", "non voglio vivere piu")
    assert out.reply == CRISIS_REPLY and provider.calls == []
    await agent.turn("res-001", "s1", "si")
    assert provider.calls[0][0] == "request_help"


async def test_emergency_escalates_immediately():
    agent, _, provider = await make_agent([])
    await agent.turn("res-001", "s1", "sono caduto e non riesco ad alzarmi")
    assert provider.calls[0][0] == "request_help" and provider.calls[0][1]["urgency"] == "alta"


async def test_tool_output_marked_untrusted():
    agent, llm, _ = await make_agent([
        ChatResult("", [ToolCall("wellbeing__mood_checkin", {"score": 3})]),
        ChatResult("Fatto."),
    ])
    await agent.turn("res-001", "s1", "mi sento cosi cosi")
    assert llm.seen_messages[-1]["content"].startswith("[dati dello strumento]")


class HashEmbedder:
    async def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 64
            for w in t.lower().split():
                v[hash(w.strip(".,:;")) % 64] += 1
            out.append(v)
        return out


async def test_rag_index_and_search(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "attivita.md").write_text("# Ginnastica dolce\nOgni martedi alle 10 in palestra.\n\n# Coro\nGiovedi alle 17.")
    kb = KnowledgeBase(tmp_path / "kb.sqlite3", HashEmbedder())
    assert await kb.index_dir(kb_dir) >= 1
    assert await kb.index_dir(kb_dir) == 0  # unchanged files are not re-embedded
    hits = await kb.search("quando c'e ginnastica dolce martedi", min_score=0.1)
    assert hits and "Ginnastica" in hits[0].text
    assert format_passages(hits).startswith("<documenti>")


def test_chunking_respects_limit():
    chunks = chunk_markdown("# A\n" + "parola " * 500, max_chars=300)
    assert all(len(c) <= 300 for c in chunks)


@pytest.mark.parametrize("schema", [{}, {"type": "object", "properties": {}}])
def test_strip_injected_handles_empty(schema):
    params, injected = _strip_injected(schema)
    assert injected == ()
