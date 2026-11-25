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
