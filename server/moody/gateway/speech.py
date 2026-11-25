"""Speech-to-text and text-to-speech over the Wyoming protocol (MIT).

STT runs faster-whisper (MIT) and TTS runs Piper in *separate containers*.
Talking to them over a socket keeps this MIT codebase cleanly separated from
Piper's GPL-3.0 engine (no linking) - see docs/10-licenze.md.
"""

from __future__ import annotations

from typing import Protocol

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncTcpClient
from wyoming.tts import Synthesize, SynthesizeVoice

from .audio import to_mono_16k


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
