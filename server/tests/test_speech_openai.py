"""OpenAI-compatible speech clients (QVAC serve --openai) against a mock server."""

import json
import struct

import httpx
import numpy as np

from moody.brain.llm import OpenAICompatClient
from moody.gateway.audio import pcm_to_wav, wav_to_pcm
from moody.gateway.speech import OpenAISTT, OpenAITTS


def test_wav_roundtrip_and_streaming_header():
    pcm = struct.pack("<4h", 1, -2, 3, -4)
    assert wav_to_pcm(pcm_to_wav(pcm, 16000)) == (pcm, 16000, 2, 1)
    streaming = bytearray(pcm_to_wav(pcm, 44100))
    streaming[40:44] = b"\xff\xff\xff\xff"  # unknown data length (streamed WAV)
    assert wav_to_pcm(bytes(streaming))[0] == pcm


async def test_stt_sends_wav_multipart_with_bearer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.content
        return httpx.Response(200, json={"text": " buongiorno a tutti "})

    stt = OpenAISTT("http://qvac:11435/v1", "moody-stt", api_key="k")
    stt._http = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=stt._http.headers)
    assert await stt.transcribe(b"\x00\x00" * 16000) == "buongiorno a tutti"
    assert seen["auth"] == "Bearer k"
    assert b'name="model"' in seen["body"] and b"moody-stt" in seen["body"] and b"RIFF" in seen["body"]


async def test_tts_resamples_44k_wav_to_16k():
    tone = (np.sin(np.arange(44100) / 10) * 3000).astype("<i2").tobytes()  # 1 s @ 44.1 kHz

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {"model": "moody-tts", "input": "Ciao", "voice": "F1", "response_format": "wav"}
        return httpx.Response(200, content=pcm_to_wav(tone, 44100), headers={"content-type": "audio/wav"})

    tts = OpenAITTS("http://qvac:11435/v1", "moody-tts", "F1")
    tts._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert len(await tts.synthesize("Ciao")) == 32000  # 1 s @ 16 kHz, 16-bit


async def test_llm_no_think_and_tool_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["messages"][0]["content"].endswith("/no_think") and body["max_tokens"] == 400
        return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "wellbeing__mood_checkin", "arguments": '{"score": 4}'}}]}}]})

    llm = OpenAICompatClient("http://qvac:11435/v1", "moody-llm", no_think=True)
    llm._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    res = await llm.chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "ciao"}], tools=[{}])
    assert res.tool_calls[0].name == "wellbeing__mood_checkin" and res.tool_calls[0].arguments == {"score": 4}
