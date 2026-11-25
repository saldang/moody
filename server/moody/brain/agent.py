"""The agent loop: guardrails -> retrieval -> LLM with tools -> guardrails.

Short-term memory only: a few turns per session, kept in RAM and dropped after
``session_ttl`` seconds of silence. Nothing conversational is persisted.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from ..common.logging import audit
from ..common.pii import redact
from .guardrails import BLOCK_REPLY, GuardModel, sanitize_output, screen_input
from .llm import LLMClient, ToolCall
from .prompts import context_message, system_prompt
from .rag import KnowledgeBase, format_passages
from .tools import ToolRegistry

log = logging.getLogger("moody.agent")

_YES = re.compile(r"^\s*(si|sì|certo|confermo|va bene|ok|okay|yes)\b", re.IGNORECASE)
_NO = re.compile(r"^\s*(no|annulla|lascia stare|stop)\b", re.IGNORECASE)
_BYE = re.compile(r"\b(grazie|basta cosi|ciao|a dopo|buonanotte)\b\W*$", re.IGNORECASE)

WEEKDAYS = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi", "sabato", "domenica"]


@dataclass
class Session:
    history: deque = field(default_factory=lambda: deque(maxlen=12))
    pending: ToolCall | None = None
    last_seen: float = field(default_factory=time.monotonic)


@dataclass
class TurnResult:
    reply: str
    end_session: bool = False
    category: str = "chat"


@dataclass
class AgentSettings:
    locale: str = "it"
    tz: str = "Europe/Rome"
    max_tool_rounds: int = 4
    session_ttl: float = 600
    log_transcripts: bool = False
    # Who gets alerted on crisis/emergency: "ask" = offer first, "auto" = notify immediately
    escalation: str = "ask"
    help_tool: str = "wellbeing.request_help"


def _mentions_tool(content: str, tool_names: set[str]) -> bool:
    lowered = (content or "").lower().replace("_", "")
    for name in tool_names:
        bare = name.split("__", 1)[-1].lower()
        if name.lower().replace("_", "") in lowered or (len(bare) > 6 and bare.replace("_", "") in lowered):
            return True
    return False


class Agent:
    def __init__(self, llm: LLMClient, tools: ToolRegistry, kb: KnowledgeBase | None,
                 settings: AgentSettings, guard: GuardModel | None = None) -> None:
        self.llm = llm
        self.tools = tools
        self.kb = kb
        self.settings = settings
        self.guard = guard
        self.sessions: dict[str, Session] = {}
        self._zone = ZoneInfo(settings.tz)

    # -- sessions -------------------------------------------------------------------
    def _session(self, key: str) -> Session:
        now = time.monotonic()
        for k in [k for k, s in self.sessions.items() if now - s.last_seen > self.settings.session_ttl]:
            del self.sessions[k]
        sess = self.sessions.setdefault(key, Session())
        sess.last_seen = now
        return sess

    def _now_local(self) -> str:
        now = dt.datetime.now(self._zone)
        return f"{WEEKDAYS[now.weekday()]} {now.strftime('%d/%m/%Y, ore %H:%M')}"

    # -- main entry -------------------------------------------------------------------
    async def turn(self, subject: str, session_id: str, text: str) -> TurnResult:
        text = (text or "").strip()
        sess = self._session(f"{subject}:{session_id}")
        if self.settings.log_transcripts:
            log.info("user turn", extra={"fields": {"subject": subject, "text": redact(text)}})
        if not text:
            return TurnResult("Non ho sentito bene. Puoi ripetere?")

        # 1. pending confirmation from a previous turn
        if sess.pending is not None:
            call, sess.pending = sess.pending, None
            if _YES.search(text):
                result = await self.tools.call(call.name, call.arguments, subject=subject)
                audit(log, "tool_confirmed", tool=call.name)
                return TurnResult(await self._summarise_action(call, result), category="tool")
            if _NO.search(text):
                return TurnResult("D'accordo, non faccio nulla.")

        # 2. deterministic guardrails
        verdict = screen_input(text)
        if verdict.action in ("crisis", "emergency"):
            audit(log, "safety_escalation", category=verdict.category)
            reply = verdict.reply
            if self.settings.escalation == "auto" or verdict.action == "emergency":
                await self.tools.call(
                    self.settings.help_tool,
                    {"reason": "emergenza segnalata a voce" if verdict.action == "emergency"
                     else "la persona ha espresso un forte disagio",
                     "urgency": "alta"},
                    subject=subject, system=True,
                )
            else:
                sess.pending = ToolCall(self.settings.help_tool,
                                        {"reason": "la persona chiede supporto", "urgency": "alta"})
            return TurnResult(reply, category=verdict.category)
        if verdict.action == "block":
            audit(log, "input_blocked", category=verdict.category)
            return TurnResult(verdict.reply, category=verdict.category)
        if self.guard is not None:
            risk = await self.guard.flagged(text)
            if risk:
                audit(log, "input_blocked", category=f"guard:{risk}")
                return TurnResult(BLOCK_REPLY, category=f"guard:{risk}")

        # 3. retrieval (non-personal knowledge only)
        context = ""
        if self.kb is not None:
            try:
                context = format_passages(await self.kb.search(text))
            except Exception as exc:  # noqa: BLE001
                log.warning("knowledge base unavailable: %s", type(exc).__name__)

        # 4. LLM + tools
        await self.tools.refresh()
        # Static system prompt first (+ tool definitions rendered by the chat template): an identical
        # prefix on every turn, reusable from the KV cache. Per-turn context rides in the user turn.
        dynamic = context_message(self._now_local(), self.settings.locale)
        if context:
            dynamic += "\n" + context
        messages: list[dict] = [{"role": "system", "content": system_prompt()}]
        messages.extend(sess.history)
        messages.append({"role": "user", "content": f"<contesto>\n{dynamic}\n</contesto>\n\n{text}"})
        tools = self.tools.llm_tools()
        tool_names = {t["function"]["name"] for t in tools}

        reply = ""
        retried = False
        for _ in range(self.settings.max_tool_rounds):
            result = await self.llm.chat(messages, tools or None)
            if not result.tool_calls:
                if not retried and _mentions_tool(result.content, tool_names):
                    # Small models sometimes *describe* a tool instead of calling it: nudge once.
                    retried = True
                    messages.append({"role": "user", "content": "Non descrivere lo strumento: chiamalo davvero, "
                                                                "oppure rispondi senza strumenti."})
                    continue
                reply = result.content
                break
            messages.append(self.llm.assistant_message(result))
            for call in result.tool_calls:
                name = self.tools.resolve(call.name)
                decision = self.tools.decide(name)
                if decision == "confirm":
                    sess.pending = ToolCall(name, call.arguments)
                    audit(log, "tool_confirmation_requested", tool=name)
                    return TurnResult(self._confirmation_question(name, call.arguments), category="confirm")
                if decision == "deny":
                    output = json.dumps({"error": "tool not allowed"})
                else:
                    output = await self.tools.call(name, call.arguments, subject=subject)
                    audit(log, "tool_called", tool=name)
                # tool output is untrusted data: label it as such for the model
                messages.append(self.llm.tool_message(call, f"[dati dello strumento]\n{output}"))
        else:
            reply = "Ho fatto il possibile, ma non sono riuscito a completare la richiesta."

        reply = sanitize_output(reply)
        sess.history.append({"role": "user", "content": text})
        sess.history.append({"role": "assistant", "content": reply})
        return TurnResult(reply, end_session=bool(_BYE.search(text)))

    # -- helpers --------------------------------------------------------------------------
    @staticmethod
    def _confirmation_question(name: str, args: dict) -> str:
        human = {
            "wellbeing.erase_my_data": "cancellare definitivamente tutti i tuoi dati",
            "wellbeing.request_help": "avvisare la persona di riferimento",
        }.get(name)
        if human is None:
            target = args.get("name") or args.get("area") or args.get("entity_id") or ""
            human = f"eseguire l'azione {name.split('.', 1)[-1]} {target}".strip()
        return f"Vuoi che proceda a {human}? Rispondi si oppure no."

    @staticmethod
    async def _summarise_action(call: ToolCall, result: str) -> str:
        try:
            data = json.loads(result)
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict) and data.get("error"):
            return "Non sono riuscito a completare l'azione, mi dispiace."
        if call.name.endswith("request_help"):
            return "Fatto, ho avvisato la persona di riferimento. Resto qui con te."
        if call.name.endswith("erase_my_data"):
            return "Fatto. Ho cancellato tutti i tuoi dati personali."
        return "Fatto."
