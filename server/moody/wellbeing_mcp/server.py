"""Wellbeing MCP server.

Every tool takes a ``subject`` argument. The brain *injects* it server-side
from the authenticated device identity and hides it from the LLM, so the model
can never read or write another resident's data (confused-deputy protection).
"""

from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

import httpx
from mcp.server import MCPServer

from ..common.logging import audit
from .store import WellbeingStore

log = logging.getLogger("moody.wellbeing")

BREATHING = {
    "box": (
        "Facciamo la respirazione quadrata. Inspira dal naso contando fino a quattro. "
        "Trattieni contando fino a quattro. Espira lentamente contando fino a quattro. "
        "Resta vuoto contando fino a quattro. Ripetiamo insieme per quattro volte, con calma."
    ),
    "4-7-8": (
        "Proviamo la respirazione quattro sette otto. Inspira dal naso per quattro secondi, "
        "trattieni il respiro per sette secondi, poi espira dalla bocca per otto secondi. "
        "Ripeti per tre o quattro cicli. Se ti gira la testa, torna a respirare normalmente."
    ),
    "coerente": (
        "Respirazione coerente: inspira dolcemente per cinque secondi ed espira per cinque secondi. "
        "Continua cosi per due minuti, lasciando le spalle morbide."
    ),
}


def build_server(
    store: WellbeingStore,
    *,
    tz: str = "Europe/Rome",
    ntfy_url: str = "",
    ntfy_topic: str = "",
    ntfy_token: str = "",
) -> MCPServer:
    zone = ZoneInfo(tz)
    mcp = MCPServer(
        "wellbeing",
        instructions="Strumenti di benessere personale. Non sono dispositivi medici.",
    )

    @mcp.tool()
    def mood_checkin(subject: str, score: int, note: str | None = None) -> dict:
        """Registra il check-in dell'umore dichiarato dalla persona (1 = molto giu, 5 = molto bene).
        Usalo solo quando la persona indica esplicitamente come si sente. La nota e' facoltativa e breve."""
        store.add_mood(subject, score, note)
        audit(log, "mood_checkin", score=score)
        return {"ok": True}

    @mcp.tool()
    def mood_summary(subject: str, days: int = 7) -> dict:
        """Riassume l'andamento dell'umore dichiarato negli ultimi N giorni (massimo 30)."""
        entries = store.mood_entries(subject, max(1, min(days, 30)))
        if not entries:
            return {"count": 0}
        scores = [e["score"] for e in entries]
        return {
            "count": len(scores),
            "average": round(sum(scores) / len(scores), 1),
            "last": scores[-1],
            "trend": "in miglioramento" if scores[-1] > scores[0] else
                     "in calo" if scores[-1] < scores[0] else "stabile",
        }

    @mcp.tool()
    def set_reminder(subject: str, text: str, at_time: str | None = None, in_minutes: int | None = None) -> dict:
        """Crea un promemoria vocale. Usa at_time nel formato HH:MM (ora locale, prossima occorrenza)
        oppure in_minutes. Promemoria per farmaci: solo come richiamo, mai indicazioni di dosaggio."""
        now = dt.datetime.now(zone)
        if in_minutes is not None:
            if not 1 <= in_minutes <= 7 * 24 * 60:
                raise ValueError("in_minutes fuori intervallo")
            due = now + dt.timedelta(minutes=in_minutes)
        elif at_time:
            hh, mm = (int(x) for x in at_time.strip().split(":", 1))
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if due <= now:
                due += dt.timedelta(days=1)
        else:
            raise ValueError("serve at_time oppure in_minutes")
        rid = store.add_reminder(subject, text, int(due.timestamp()))
        audit(log, "reminder_set")
        return {"id": rid, "due_local": due.strftime("%d/%m %H:%M")}

    @mcp.tool()
    def list_reminders(subject: str) -> dict:
        """Elenca i promemoria attivi della persona."""
        return {
            "reminders": [
                {"id": r.id, "text": r.text,
                 "due_local": dt.datetime.fromtimestamp(r.due_ts, zone).strftime("%d/%m %H:%M")}
                for r in store.list_reminders(subject)
            ]
        }

    @mcp.tool()
    def cancel_reminder(subject: str, reminder_id: int) -> dict:
        """Cancella un promemoria esistente dato il suo id."""
        return {"ok": store.cancel_reminder(subject, reminder_id)}

    @mcp.tool()
    def due_reminders(subject: str) -> dict:
        """(Uso interno del sistema) Restituisce e marca come consegnati i promemoria scaduti."""
        return {"due": [r.text for r in store.pop_due(subject)]}

    @mcp.tool()
    def breathing_exercise(subject: str, kind: str = "box") -> dict:
        """Restituisce il testo di un esercizio di respirazione guidata: box, 4-7-8 oppure coerente."""
        return {"script": BREATHING.get(kind, BREATHING["box"])}

    @mcp.tool()
    def erase_my_data(subject: str) -> dict:
        """Cancella definitivamente tutti i dati personali della persona (diario umore e promemoria)."""
        n = store.erase_subject(subject)
        audit(log, "erase_subject", rows=n)
        return {"ok": True, "deleted": n}

    @mcp.tool()
    async def request_help(subject: str, reason: str, urgency: str = "normale") -> dict:
        """Avvisa il contatto di fiducia (casa) o lo staff (struttura) che la persona chiede aiuto.
        urgency: normale oppure alta. NON sostituisce il 112."""
        if not ntfy_url or not ntfy_topic:
            return {"sent": False, "detail": "nessun canale di notifica configurato"}
        headers = {
            "Title": "Moody: richiesta di aiuto",
            "Priority": "urgent" if urgency == "alta" else "high",
            "Tags": "sos" if urgency == "alta" else "wave",
        }
        if ntfy_token:
            headers["Authorization"] = f"Bearer {ntfy_token}"
        # Only the pseudonym and a short reason leave this service: staff map the
        # pseudonym to a person/room in their own care system.
        body = f"Dispositivo {subject}: {reason.strip()[:140]}"
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            resp = await client.post(f"{ntfy_url.rstrip('/')}/{ntfy_topic}", content=body.encode(), headers=headers)
        audit(log, "help_requested", urgency=urgency, status=resp.status_code)
        return {"sent": resp.status_code < 300}

    return mcp
