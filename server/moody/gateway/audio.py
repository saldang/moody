"""Audio helpers (numpy only; no GPL resamplers)."""

from __future__ import annotations

import numpy as np


def to_mono_16k(pcm: bytes, rate: int, width: int, channels: int, target_rate: int = 16000) -> bytes:
    if width != 2:
        raise ValueError("only 16-bit PCM is supported")
    samples = np.frombuffer(pcm, dtype="<i2")
    if channels > 1:
        samples = samples[: len(samples) - len(samples) % channels].reshape(-1, channels).mean(axis=1)
    samples = samples.astype(np.float32)
    if rate != target_rate and len(samples):
        n_out = int(round(len(samples) * target_rate / rate))
        x_old = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        samples = np.interp(x_new, x_old, samples)
    return np.clip(samples, -32768, 32767).astype("<i2").tobytes()


def rms(pcm: bytes) -> float:
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    return float(np.sqrt(np.mean(samples**2))) if len(samples) else 0.0


def pcm_to_wav(pcm: bytes, rate: int = 16000, channels: int = 1, width: int = 2) -> bytes:
    """Wrap raw PCM in a minimal RIFF/WAVE header (in memory, never written to disk)."""
    import struct

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, channels, rate,
        rate * channels * width, channels * width, width * 8, b"data", len(pcm),
    )
    return header + pcm


def wav_to_pcm(wav: bytes) -> tuple[bytes, int, int, int]:
    """Parse a PCM WAV (also streaming headers with unknown length). Returns (pcm, rate, width, channels)."""
    import struct

    if wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    pos, fmt = 12, None
    while pos + 8 <= len(wav):
        cid, size = wav[pos:pos + 4], struct.unpack("<I", wav[pos + 4:pos + 8])[0]
        body = pos + 8
        if cid == b"fmt ":
            tag, channels, rate, _, _, bits = struct.unpack("<HHIIHH", wav[body:body + 16])
            if tag not in (1, 0xFFFE):
                raise ValueError("only PCM WAV is supported")
            fmt = (rate, bits // 8, channels)
        elif cid == b"data":
            if fmt is None:
                raise ValueError("WAV data before fmt chunk")
            end = len(wav) if size in (0, 0xFFFFFFFF) else min(len(wav), body + size)
            return wav[body:end], *fmt
        pos = body + size + (size & 1)
    raise ValueError("WAV without data chunk")
