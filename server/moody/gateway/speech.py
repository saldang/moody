"""Speech-to-text and text-to-speech backends.

* ``OpenAISTT`` / ``OpenAITTS`` - OpenAI-compatible audio API. Default: the QVAC
  server by Tether (``qvac serve --openai``) with TranscribePsy (STT) and
  Supertonic 3 (TTS), see docs/13-qvac.md.
* ``WyomingSTT`` / ``WyomingTTS`` - Wyoming protocol (MIT): faster-whisper and Piper.
  Piper's engine is GPL-3.0: it runs in a *separate container* and we only talk to
  it over a socket, which keeps this MIT codebase cleanly separated (docs/10-licenze.md).
"""

from __future__ import annotations

from typing import Protocol

import httpx
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.tts import Synthesize, SynthesizeVoice

from .audio import pcm_to_wav, to_mono_16k, wav_to_pcm


class STT(Protocol):
    async def transcribe(self, pcm: bytes, rate: int = 16000) -> str: ...


class TTS(Protocol):
    async def synthesize(self, text: str) -> bytes:
        """Return PCM s16le mono 16 kHz."""
        ...


class WyomingSTT:
    def __init__(self, host: str, port: int, language: str = "it") -> None:
        self.host, self.port, self.language = host, port, language

    async def transcribe(self, pcm: bytes, rate: int = 16000) -> str:
        async with AsyncTcpClient(self.host, self.port) as client:
            await client.write_event(Transcribe(language=self.language).event())
            await client.write_event(AudioStart(rate=rate, width=2, channels=1).event())
            for i in range(0, len(pcm), 3200):
                await client.write_event(AudioChunk(rate=rate, width=2, channels=1, audio=pcm[i:i + 3200]).event())
            await client.write_event(AudioStop().event())
            while True:
                event = await client.read_event()
                if event is None:
                    return ""
                if Transcript.is_type(event.type):
                    return Transcript.from_event(event).text.strip()


class WyomingTTS:
    def __init__(self, host: str, port: int, voice: str = "it_IT-paola-medium") -> None:
        self.host, self.port, self.voice = host, port, voice

    async def synthesize(self, text: str) -> bytes:
        chunks: list[bytes] = []
        fmt = (22050, 2, 1)
        async with AsyncTcpClient(self.host, self.port) as client:
            await client.write_event(Synthesize(text=text, voice=SynthesizeVoice(name=self.voice)).event())
            while True:
                event = await client.read_event()
                if event is None or AudioStop.is_type(event.type):
                    break
                if AudioStart.is_type(event.type):
                    start = AudioStart.from_event(event)
                    fmt = (start.rate, start.width, start.channels)
                elif AudioChunk.is_type(event.type):
                    chunks.append(AudioChunk.from_event(event).audio)
        return to_mono_16k(b"".join(chunks), *fmt)


class OpenAISTT:
    """``POST {base}/audio/transcriptions`` (multipart WAV). Language is fixed at model load in QVAC."""

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(trust_env=False, timeout=timeout, headers=headers)

    async def transcribe(self, pcm: bytes, rate: int = 16000) -> str:
        resp = await self._http.post(
            f"{self.base_url}/audio/transcriptions",
            files={"file": ("utterance.wav", pcm_to_wav(pcm, rate), "audio/wav")},
            data={"model": self.model, "response_format": "json"},
        )
        resp.raise_for_status()
        return str(resp.json().get("text", "")).strip()


class OpenAITTS:
    """``POST {base}/audio/speech`` returning WAV; converted to PCM s16le mono 16 kHz."""

    def __init__(self, base_url: str, model: str, voice: str, api_key: str = "", timeout: float = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.voice = voice
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(trust_env=False, timeout=timeout, headers=headers)

    async def synthesize(self, text: str) -> bytes:
        resp = await self._http.post(
            f"{self.base_url}/audio/speech",
            json={"model": self.model, "input": text, "voice": self.voice, "response_format": "wav"},
        )
        resp.raise_for_status()
        pcm, rate, width, channels = wav_to_pcm(resp.content)
        return to_mono_16k(pcm, rate, width, channels)
