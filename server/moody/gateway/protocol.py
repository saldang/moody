"""Edge <-> gateway protocol ("moody.v1"), see docs/12-protocollo.md.

Text frames carry small JSON control messages; binary frames carry raw
PCM s16le mono 16 kHz audio. Audio only flows *after* the on-device wake
word (or a tap on the screen): the gateway never receives ambient sound.
"""

from __future__ import annotations

import json
import unicodedata
from typing import Any

SUBPROTOCOL = "moody.v1"
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
MAX_UTTERANCE_SECONDS = 15
MAX_UTTERANCE_BYTES = SAMPLE_RATE * SAMPLE_WIDTH * MAX_UTTERANCE_SECONDS
MAX_FRAME_BYTES = 8192
MAX_CONTROL_BYTES = 1024
TTS_CHUNK_BYTES = 4096

DEVICE_MESSAGES = {"hello", "listen_start", "listen_end", "abort"}


class ProtocolError(ValueError):
    pass


def parse_control(raw: str) -> dict[str, Any]:
    if len(raw) > MAX_CONTROL_BYTES:
        raise ProtocolError("control message too large")
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError("invalid json") from exc
    if not isinstance(msg, dict) or msg.get("type") not in DEVICE_MESSAGES:
        raise ProtocolError("unknown message type")
    return msg


def msg(type_: str, **fields: Any) -> str:
    return json.dumps({"type": type_, **fields}, ensure_ascii=True)


def display_text(text: str, limit: int = 220) -> str:
    """ASCII-fold text for the device display (built-in LVGL fonts are ASCII only).

    Accented vowels become ``e'``-style, the Italian convention for plain ASCII.
    """
    out = []
    for ch in text:
        base = unicodedata.normalize("NFKD", ch)
        if base != ch and base[0].isascii() and any(unicodedata.combining(c) for c in base[1:]):
            out.append(base[0] + "'")
        elif ch.isascii():
            out.append(ch)
        elif ch in "‘’":
            out.append("'")
        elif ch in "“”":
            out.append('"')
        elif ch in "–—":
            out.append("-")
        else:
            out.append(" ")
    folded = "".join(out)
    return folded if len(folded) <= limit else folded[: limit - 3] + "..."
