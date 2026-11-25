import json
import sqlite3

import pytest
from cryptography.fernet import Fernet
from mcp import Client

from moody.wellbeing_mcp.server import build_server
from moody.wellbeing_mcp.store import WellbeingStore


@pytest.fixture()
def store(tmp_path):
    return WellbeingStore(tmp_path / "wb.sqlite3", Fernet.generate_key().decode(), retention_days=30)


def test_mood_is_encrypted_and_pseudonymised(store, tmp_path):
    store.add_mood("res-001", 4, "mi sento sereno dopo la passeggiata")
    raw = sqlite3.connect(tmp_path / "wb.sqlite3").execute("SELECT subject, payload FROM mood").fetchone()
    assert raw[0] != "res-001" and len(raw[0]) == 64
    assert b"passeggiata" not in raw[1]
    assert store.mood_entries("res-001", 7)[0]["note"].startswith("mi sento")
    assert store.mood_entries("res-002", 7) == []


def test_score_validation(store):
    with pytest.raises(ValueError):
        store.add_mood("res-001", 9, None)


def test_retention_and_erasure(store):
    store.add_mood("res-001", 3, None, now=1_000)
    store.add_mood("res-001", 4, None)
    store.add_reminder("res-001", "acqua", due_ts=2_000_000_000)
    assert store.purge_expired() == 1
    assert store.erase_subject("res-001") == 2
    assert store.export_subject("res-001") == {"mood": [], "reminders": []}


def test_due_reminders_are_delivered_once(store):
    store.add_reminder("res-001", "bere un bicchiere d'acqua", due_ts=10)
    assert [r.text for r in store.pop_due("res-001", now=20)] == ["bere un bicchiere d'acqua"]
    assert store.pop_due("res-001", now=30) == []


def test_bad_key_rejected(tmp_path):
    with pytest.raises(ValueError):
        WellbeingStore(tmp_path / "x.db", "c2hvcnQ=")


async def test_mcp_tools_end_to_end(store):
    server = build_server(store)
    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert {"mood_checkin", "set_reminder", "erase_my_data", "request_help"} <= names
        await client.call_tool("mood_checkin", {"subject": "res-001", "score": 5})
        res = await client.call_tool("mood_summary", {"subject": "res-001"})
        assert json.loads(res.content[0].text)["count"] == 1
        res = await client.call_tool("set_reminder", {"subject": "res-001", "text": "pillola", "in_minutes": 5})
        assert "due_local" in json.loads(res.content[0].text)
        res = await client.call_tool("request_help", {"subject": "res-001", "reason": "test"})
        assert json.loads(res.content[0].text)["sent"] is False  # no channel configured
