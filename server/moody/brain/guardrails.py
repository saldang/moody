"""Deterministic guardrails that run *before* and *after* the LLM.

Open-source replacement for the managed "prompt shields / content safety"
layer. Defence in depth:

1. Rule-based input screening (always on, no model needed, auditable).
   Crisis and emergency phrases bypass the LLM entirely and return a fixed,
   reviewed answer: we never let a probabilistic model improvise there.
2. Optional model-based screening (IBM Granite Guardian, Apache-2.0, via Ollama).
3. Output sanitisation: voice-friendly text, length cap, medical-dosage filter.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

import httpx

log = logging.getLogger("moody.guardrails")

Action = Literal["allow", "crisis", "emergency", "block"]

MAX_INPUT_CHARS = 1000
MAX_OUTPUT_CHARS = 700


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text)


_CRISIS = [
    r"\b(voglio|vorrei) (morire|farla finita|sparire per sempre)",
    r"\bfarla finita\b",
    r"\b(uccidermi|ammazzarmi|suicid\w*|togliermi la vita)\b",
    r"\bfarmi del male\b",
    r"\bnon (voglio|ce la faccio a) vivere\b",
    r"\b(kill myself|end my life|suicid\w*|self[- ]harm)\b",
]
_EMERGENCY = [
    r"\bsono cadut[oaie]\b",
    r"\b(e|e') cadut[oa]\b",
    r"\bnon riesco (ad? alzarmi|a respirare)\b",
    r"\bnon respiro\b",
    r"\bdolore (forte )?al petto\b",
    r"\b(infarto|ictus)\b",
    r"\bchiama (un'?ambulanza|il 112|il 118|aiuto)\b",
    r"\b(i('ve)? fallen|can'?t breathe|chest pain|call an ambulance)\b",
]
_INJECTION = [
    r"ignora (tutte )?(le )?(istruzioni|regole)",
    r"ignore (all |any )?(previous|prior|above) (instructions|rules)",
    r"(system prompt|prompt di sistema)",
    r"\b(developer|sviluppatore|dan|jailbreak) mode\b",
    r"\bfingi di essere\b.*\bsenza (regole|limiti)\b",
    r"<\s*/?\s*(system|tool|assistant)\s*>",
    r"\[\[?\s*(system|inst)\s*\]?\]",
]

CRISIS_REPLY = (
    "Mi dispiace molto che tu stia soffrendo cosi, e ti ringrazio di avermelo detto. "
    "Non sei solo. Se sei in pericolo adesso chiama subito il 112. "
    "Puoi parlare con qualcuno anche ora: Telefono Amico risponde allo 02 2327 2327. "
    "Se vuoi, avviso subito una persona di fiducia."
)
EMERGENCY_REPLY = (
    "Sembra un'emergenza. Se puoi, chiama subito il 112. "
    "Sto avvisando la persona di riferimento. Resta dove sei e cerca di stare tranquillo."
)
BLOCK_REPLY = "Questo non posso farlo, ma sono qui se vuoi parlare d'altro o hai bisogno di una mano."


@dataclass
class InputVerdict:
    action: Action
    category: str = ""
    reply: str = ""
    reasons: list[str] = field(default_factory=list)


def screen_input(text: str) -> InputVerdict:
    """Rule-based screening. Order matters: safety of the person comes first."""
    if len(text) > MAX_INPUT_CHARS:
        return InputVerdict("block", "too_long", BLOCK_REPLY)
    norm = _norm(text)
    for pat in _CRISIS:
        if re.search(pat, norm):
            return InputVerdict("crisis", "self_harm", CRISIS_REPLY, [pat])
    for pat in _EMERGENCY:
        if re.search(pat, norm):
            return InputVerdict("emergency", "medical_emergency", EMERGENCY_REPLY, [pat])
    for pat in _INJECTION:
        if re.search(pat, norm):
            return InputVerdict("block", "prompt_injection", BLOCK_REPLY, [pat])
    return InputVerdict("allow")


# --- output ------------------------------------------------------------------------
_DOSAGE = re.compile(
    r"\b\d+([.,]\d+)?\s?(mg|mcg|µg|ml|gocce|compresse|pastiglie|unita|ui)\b.*"
    r"\b(al giorno|ogni|volte|prima|dopo|dose)\b",
    re.IGNORECASE,
)
DOSAGE_REPLY = (
    "Su farmaci e dosaggi non posso darti indicazioni: e' meglio chiedere al medico o al farmacista. "
    "Se vuoi posso impostarti un promemoria."
)
_MD = re.compile(r"(\*\*|__|`+|#+\s|^\s*[-*]\s+|\[(.*?)\]\((.*?)\))", re.MULTILINE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def sanitize_output(text: str) -> str:
    """Make LLM output safe and pleasant for text-to-speech."""
    text = _THINK.sub("", text or "")
    if _DOSAGE.search(_norm(text)):
        return DOSAGE_REPLY
    text = _MD.sub(lambda m: m.group(2) or "", text)
    text = _EMOJI.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_OUTPUT_CHARS:
        cut = text[:MAX_OUTPUT_CHARS]
        text = cut[: max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! ")) + 1] or cut
    return text or "Scusa, non ho capito bene. Puoi ripetere?"


class GuardModel:
    """Optional second opinion from a local safety classifier (Granite Guardian).

    Granite Guardian answers "Yes" when the given risk is present. We fail *open*
    on infrastructure errors (rules above are still active) and log it.
    """

    def __init__(self, base_url: str, model: str, risks: tuple[str, ...] = ("jailbreak", "harm")) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.risks = risks

    async def flagged(self, text: str) -> str | None:
        async with httpx.AsyncClient(trust_env=False, timeout=20) as client:
            for risk in self.risks:
                try:
                    resp = await client.post(
                        f"{self.base_url}/api/chat",
                        json={
                            "model": self.model,
                            "stream": False,
                            "messages": [{"role": "system", "content": risk},
                                         {"role": "user", "content": text}],
                            "options": {"temperature": 0},
                        },
                    )
                    resp.raise_for_status()
                    answer = resp.json()["message"]["content"].strip().lower()
                except Exception as exc:  # noqa: BLE001
                    log.warning("guard model unavailable: %s", type(exc).__name__)
                    return None
                if answer.startswith("yes"):
                    return risk
        return None
