"""Edge gateway: the only Moody service reachable from the LAN.

Responsibilities (open-source counterpart of the original "Python sandbox"):

* Terminate WSS with **mutual TLS**: devices authenticate with a certificate
  issued by the device CA; the gateway authenticates with a service-CA cert.
* Authorise the device against the registry (enabled, not revoked).
* Run the voice pipeline: audio -> STT -> brain -> TTS -> audio.
* Push due reminders, respecting per-device quiet hours.
* Enforce protocol limits (frame size, utterance length, idle timeout).

It deliberately has **no** generic network access tools (no scanning, no MAC
lookups): home automation goes through an allow-listed MCP server instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
import secrets
import ssl
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from zoneinfo import ZoneInfo

from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from ..common.logging import audit
from ..common.tls import peer_identity
from .brain_client import BrainClient
from .devices import Device, DeviceRegistry
from .protocol import (
    MAX_FRAME_BYTES,
    MAX_UTTERANCE_BYTES,
    SUBPROTOCOL,
    TTS_CHUNK_BYTES,
    ProtocolError,
    display_text,
    msg,
    parse_control,
)
from .speech import STT, TTS

log = logging.getLogger("moody.gateway")


@dataclass
class GatewaySettings:
    host: str = "0.0.0.0"  # noqa: S104 - must be reachable by devices on the LAN/VLAN
    port: int = 8443
    tz: str = "Europe/Rome"
    notify_interval: float = 30
    idle_timeout: float = 300
    max_connections: int = 200
    min_speech_rms: float = 120.0
    firmware_dir: Path | None = None  # contains moody_edge.bin + version.txt (signed release image)


FIRMWARE_PATH = "/v1/firmware/moody_edge.bin"


def _ver(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.strip().split(".")[:3])
    except ValueError:
        return (0,)


@dataclass
class _Conn:
    device: Device
    session_id: str
    listening: bool = False
    buffer: bytearray = field(default_factory=bytearray)
    speaking: asyncio.Task | None = None
    busy: asyncio.Lock = field(default_factory=asyncio.Lock)


class Gateway:
    def __init__(self, registry: DeviceRegistry, stt: STT, tts: TTS, brain: BrainClient,
                 ssl_context: ssl.SSLContext, settings: GatewaySettings | None = None) -> None:
        self.registry = registry
        self.stt = stt
        self.tts = tts
        self.brain = brain
        self.ssl_context = ssl_context
        self.settings = settings or GatewaySettings()
        self._zone = ZoneInfo(self.settings.tz)
        self._active: dict[str, ServerConnection] = {}

    # -- server lifecycle -------------------------------------------------------------
    def serve(self):  # noqa: ANN201 - returns websockets' async context manager
        return serve(
            self._handler,
            self.settings.host,
            self.settings.port,
            ssl=self.ssl_context,
            process_request=self._authorize,
            subprotocols=[SUBPROTOCOL],
            max_size=MAX_FRAME_BYTES,
            max_queue=32,
            ping_interval=20,
            ping_timeout=20,
            server_header=None,
        )

    def _authorize(self, ws: ServerConnection, request: Request) -> Response | None:
        """Runs *before* the WebSocket upgrade: unknown, disabled or revoked devices get a 403."""
        try:
            cn, serial = peer_identity(ws.transport.get_extra_info("peercert"))
            ws.moody_device = self.registry.authorize(cn, serial)  # type: ignore[attr-defined]
        except PermissionError as exc:
            audit(log, "device_rejected", reason=str(exc))
            return ws.respond(HTTPStatus.FORBIDDEN, "forbidden\n")
        if request.path == FIRMWARE_PATH:
            return self._firmware_response(ws)
        if len(self._active) >= self.settings.max_connections:
            return ws.respond(HTTPStatus.SERVICE_UNAVAILABLE, "busy\n")
        return None

    # -- OTA ------------------------------------------------------------------------------
    def firmware_version(self) -> str | None:
        d = self.settings.firmware_dir
        if d is None or not (d / "version.txt").is_file() or not (d / "moody_edge.bin").is_file():
            return None
        return (d / "version.txt").read_text().strip()

    def _firmware_response(self, ws: ServerConnection) -> Response:
        """Serve the firmware image to authenticated devices only (same mTLS as the WebSocket).

        Integrity is NOT based on this channel alone: with Secure Boot V2 the device verifies the
        image signature (CONFIG_SECURE_SIGNED_ON_UPDATE) and refuses unsigned or foreign builds.
        """
        if self.firmware_version() is None:
            return ws.respond(HTTPStatus.NOT_FOUND, "no firmware\n")
        body = (self.settings.firmware_dir / "moody_edge.bin").read_bytes()  # type: ignore[operator]
        audit(log, "firmware_download", device=ws.moody_device.device_id)  # type: ignore[attr-defined]
        headers = Headers([("Content-Type", "application/octet-stream"), ("Content-Length", str(len(body)))])
        return Response(200, "OK", headers, body)

    async def _handler(self, ws: ServerConnection) -> None:
        device: Device = ws.moody_device  # type: ignore[attr-defined]
        # One live connection per device: a cloned certificate kicks the other off (and is visible in logs).
        old = self._active.get(device.device_id)
        if old is not None:
            audit(log, "device_duplicate_connection", device=device.device_id)
            await old.close(4009, "replaced")
        self._active[device.device_id] = ws
        conn = _Conn(device, secrets.token_hex(8))
        audit(log, "device_connected", device=device.device_id)
        notifier = asyncio.create_task(self._notify_loop(ws, conn))
        try:
            await self._loop(ws, conn)
        except ConnectionClosed:
            pass
        except ProtocolError as exc:
            audit(log, "protocol_error", device=device.device_id, reason=str(exc))
            await ws.close(1008, "protocol error")
        finally:
            notifier.cancel()
            if conn.speaking:
                conn.speaking.cancel()
            if self._active.get(device.device_id) is ws:
                del self._active[device.device_id]
            audit(log, "device_disconnected", device=device.device_id)

    async def _loop(self, ws: ServerConnection, conn: _Conn) -> None:
        while True:
            try:
                frame = await asyncio.wait_for(ws.recv(), timeout=self.settings.idle_timeout)
            except TimeoutError:
                await ws.close(1000, "idle")
                return
            if isinstance(frame, bytes):
                if not conn.listening:
                    continue  # never accept audio outside an explicit listening window
                conn.buffer.extend(frame)
                if len(conn.buffer) >= MAX_UTTERANCE_BYTES:
                    await self._finish_utterance(ws, conn)
                continue
            message = parse_control(frame)
            kind = message["type"]
            if kind == "hello":
                extra = {}
                latest = self.firmware_version()
                if latest and _ver(latest) > _ver(str(message.get("fw", "0"))):
                    extra["ota"] = {"version": latest, "path": FIRMWARE_PATH}
                    audit(log, "ota_offered", device=conn.device.device_id, version=latest)
                await ws.send(msg("hello_ack", session=conn.session_id, proto=1, **extra))
            elif kind == "listen_start":
                if conn.speaking:
                    conn.speaking.cancel()
                conn.listening = True
                conn.buffer.clear()
            elif kind == "listen_end":
                await self._finish_utterance(ws, conn)
            elif kind == "abort":
                conn.listening = False
                conn.buffer.clear()
                if conn.speaking:
                    conn.speaking.cancel()
                await ws.send(msg("state", value="idle"))

    # -- pipeline -----------------------------------------------------------------------
    async def _finish_utterance(self, ws: ServerConnection, conn: _Conn) -> None:
        if not conn.listening:
            return
        conn.listening = False
        audio = bytes(conn.buffer)
        conn.buffer.clear()  # audio is never written to disk and dropped right after STT
        conn.speaking = asyncio.create_task(self._respond(ws, conn, audio))

    async def _respond(self, ws: ServerConnection, conn: _Conn, audio: bytes) -> None:
        from .audio import rms

        async with conn.busy:
            try:
                await ws.send(msg("state", value="thinking"))
                if len(audio) < 16000 or rms(audio) < self.settings.min_speech_rms:  # < 0.5 s or silence
                    await ws.send(msg("state", value="idle"))
                    return
                started = time.monotonic()
                text = await self.stt.transcribe(audio)
                del audio
                if not text:
                    await self._speak(ws, "Non ho capito bene, puoi ripetere?", follow_up=True)
                    return
                await ws.send(msg("stt", display=display_text(text)))
                result = await self.brain.turn(conn.device.subject, conn.session_id, text)
                reply = result.get("reply", "")
                follow_up = result.get("category") == "confirm" or reply.rstrip().endswith("?")
                await self._speak(ws, reply, follow_up=follow_up and not result.get("end_session"))
                audit(log, "turn_completed", device=conn.device.device_id,
                      category=result.get("category", "chat"),
                      latency_ms=int((time.monotonic() - started) * 1000))
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await ws.send(msg("tts_end", follow_up=False))
                raise
            except ConnectionClosed:
                raise
            except Exception:
                log.exception("pipeline error")
                with contextlib.suppress(Exception):
                    await ws.send(msg("state", value="error"))

    async def _speak(self, ws: ServerConnection, text: str, follow_up: bool = False) -> None:
        pcm = await self.tts.synthesize(text)
        await ws.send(msg("reply", display=display_text(text)))
        await ws.send(msg("tts_start", rate=16000))
        for i in range(0, len(pcm), TTS_CHUNK_BYTES):
            await ws.send(pcm[i:i + TTS_CHUNK_BYTES])
        await ws.send(msg("tts_end", follow_up=follow_up))

    async def _notify_loop(self, ws: ServerConnection, conn: _Conn) -> None:
        while True:
            await asyncio.sleep(self.settings.notify_interval)
            now = dt.datetime.now(self._zone).time()
            if conn.device.in_quiet_hours(now) or conn.listening or conn.busy.locked():
                continue
            try:
                items = await self.brain.notifications(conn.device.subject)
            except Exception as exc:  # noqa: BLE001
                log.debug("notifications unavailable: %s", type(exc).__name__)
                continue
            for text in items:
                async with conn.busy:
                    await self._speak(ws, text)
