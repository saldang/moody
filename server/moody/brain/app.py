"""Brain HTTP API (internal network only, mTLS enforced by the server)."""

from __future__ import annotations

import json
import logging
import re

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from .agent import Agent
from .auth import OIDCVerifier, make_dependency

log = logging.getLogger("moody.brain")

_ID = r"^[A-Za-z0-9_.:-]{1,64}$"


class TurnIn(BaseModel):
    subject: str = Field(pattern=_ID)
    session_id: str = Field(pattern=_ID)
    text: str = Field(max_length=1000)


class TurnOut(BaseModel):
    reply: str
    end_session: bool = False
    category: str = "chat"


def create_app(agent: Agent, verifier: OIDCVerifier | None = None) -> FastAPI:
    app = FastAPI(title="moody-brain", docs_url=None, redoc_url=None, openapi_url=None)
    auth = make_dependency(verifier)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True}

    @app.post("/v1/turn", response_model=TurnOut)
    async def turn(body: TurnIn, _claims: dict | None = Depends(auth)) -> TurnOut:
        try:
            result = await agent.turn(body.subject, body.session_id, body.text)
        except Exception:
            log.exception("turn failed")
            return TurnOut(reply="Scusa, ho avuto un problema tecnico. Riprova tra poco.", category="error")
        return TurnOut(reply=result.reply, end_session=result.end_session, category=result.category)

    @app.get("/v1/notifications")
    async def notifications(subject: str, _claims: dict | None = Depends(auth)) -> dict:
        if not re.match(_ID, subject):
            return {"items": []}
        try:
            raw = await agent.tools.call("wellbeing.due_reminders", {}, subject=subject, system=True)
            due = json.loads(raw).get("due", [])
        except Exception:  # noqa: BLE001
            return {"items": []}
        return {"items": [f"Promemoria: {text}" for text in due]}

    return app
