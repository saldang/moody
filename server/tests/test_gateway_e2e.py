import asyncio
import json
import math
import ssl
import struct

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from moody import pki
from moody.common.tls import TLSFiles, server_context
from moody.gateway.devices import DeviceRegistry
from moody.gateway.server import Gateway, GatewaySettings


class FakeSTT:
    async def transcribe(self, pcm, rate=16000):
        assert len(pcm) >= 16000
        return "che attività ci sono oggi?"


class FakeTTS:
    async def synthesize(self, text):
        return b"\x01\x00" * 8000  # 0.5 s


class FakeBrain:
    def __init__(self):
        self.turns = []

    async def turn(self, subject, session_id, text):
        self.turns.append((subject, text))
        return {"reply": "Oggi alle dieci c'è ginnastica dolce. Vuoi un promemoria?", "category": "chat"}

    async def notifications(self, subject):
        return []


def tone(seconds=1.0):
    n = int(16000 * seconds)
    return b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(n))


@pytest.fixture()
def gateway_factory(pki_dir, tmp_path):
    async def _start(devices_yaml: str, firmware_dir=None):
        devfile = tmp_path / "devices.yaml"
        devfile.write_text(devices_yaml)
        svc = pki_dir / "services" / "gateway"
        ctx = server_context(TLSFiles(svc / "tls.pem", svc / "tls.key", pki_dir / "device-ca" / "ca.pem"),
                             allow_tls12=True)
        brain = FakeBrain()
        gw = Gateway(DeviceRegistry(devfile), FakeSTT(), FakeTTS(), brain, ctx,
                     GatewaySettings(host="127.0.0.1", port=0, notify_interval=3600,
                                     firmware_dir=firmware_dir))
        server = await gw.serve().__aenter__()
        port = next(iter(server.sockets)).getsockname()[1]
        return server, port, brain
    return _start


def client_ctx(pki_dir, cert, key):
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(pki_dir / "service-ca" / "ca.pem"))
    ctx.load_cert_chain(str(cert), str(key))
    return ctx


async def test_full_voice_turn(pki_dir, device_cert, gateway_factory):
    cert, key, _ = device_cert("moody-test01")
    server, port, brain = await gateway_factory("devices:\n  moody-test01:\n    subject: res-001\n")
    try:
        async with connect(f"wss://localhost:{port}/v1/ws", ssl=client_ctx(pki_dir, cert, key),
                           subprotocols=["moody.v1"]) as ws:
            await ws.send(json.dumps({"type": "hello", "fw": "test"}))
            assert json.loads(await ws.recv())["type"] == "hello_ack"
            await ws.send(b"\x00" * 3200)  # audio before listen_start must be ignored
            await ws.send(json.dumps({"type": "listen_start"}))
            pcm = tone(1.0)
            for i in range(0, len(pcm), 1024):
                await ws.send(pcm[i:i + 1024])
            await ws.send(json.dumps({"type": "listen_end"}))
            seen, audio = [], 0
            while True:
                frame = await asyncio.wait_for(ws.recv(), 5)
                if isinstance(frame, bytes):
                    audio += len(frame)
                    continue
                m = json.loads(frame)
                seen.append(m["type"])
                if m["type"] == "stt":
                    assert m["display"] == "che attivita' ci sono oggi?"
                if m["type"] == "tts_end":
                    assert m["follow_up"] is True  # reply ends with a question
                    break
            assert seen == ["state", "stt", "reply", "tts_start", "tts_end"]
            assert audio == 16000
        assert brain.turns == [("res-001", "che attività ci sono oggi?")]
    finally:
        server.close()


@pytest.mark.parametrize("yaml_tpl", [
    "devices: {}\n",                                                    # unknown device
    "devices:\n  moody-test01:\n    enabled: false\n",                  # disabled
    "devices:\n  moody-test01: {}\nrevoked_serials: ['{serial}']\n",    # revoked
])
async def test_unauthorised_devices_rejected(pki_dir, device_cert, gateway_factory, yaml_tpl):
    cert, key, serial = device_cert("moody-test01")
    server, port, _ = await gateway_factory(yaml_tpl.replace("{serial}", serial))
    try:
        with pytest.raises(InvalidStatus) as exc:
            async with connect(f"wss://localhost:{port}/", ssl=client_ctx(pki_dir, cert, key)):
                pass
        assert exc.value.response.status_code == 403
    finally:
        server.close()


async def test_service_cert_cannot_connect_as_device(pki_dir, gateway_factory):
    """A certificate from the *service* CA must be refused at the TLS layer."""
    svc = pki_dir / "services" / "gateway"
    server, port, _ = await gateway_factory("devices:\n  gateway: {}\n")
    try:
        with pytest.raises((ssl.SSLError, ConnectionClosed, InvalidHandshake, OSError)):
            async with connect(f"wss://localhost:{port}/", ssl=client_ctx(pki_dir, svc / "tls.pem", svc / "tls.key")) as ws:
                await ws.send(json.dumps({"type": "hello"}))
                await asyncio.wait_for(ws.recv(), 5)
    finally:
        server.close()


def test_pki_rejects_bad_csr(pki_dir):
    from conftest import make_csr
    csr, _ = make_csr("moody-aaa111")
    with pytest.raises(ValueError):
        pki.sign_device_csr(pki_dir, csr, expected_cn="moody-bbb222")
    csr, _ = make_csr("not-a-device")
    with pytest.raises(ValueError):
        pki.sign_device_csr(pki_dir, csr)


async def test_ota_offer_and_download(pki_dir, device_cert, gateway_factory, tmp_path):
    import httpx

    fw = tmp_path / "fw"
    fw.mkdir()
    (fw / "moody_edge.bin").write_bytes(b"\xe9" + b"\x00" * 1023)
    (fw / "version.txt").write_text("0.2.0\n")
    cert, key, _ = device_cert("moody-test01")
    server, port, _ = await gateway_factory("devices:\n  moody-test01: {}\n", firmware_dir=fw)
    try:
        ctx = client_ctx(pki_dir, cert, key)
        async with connect(f"wss://localhost:{port}/v1/ws", ssl=ctx, subprotocols=["moody.v1"]) as ws:
            await ws.send(json.dumps({"type": "hello", "fw": "0.1.0"}))
            ack = json.loads(await ws.recv())
            assert ack["ota"] == {"version": "0.2.0", "path": "/v1/firmware/moody_edge.bin"}
        async with connect(f"wss://localhost:{port}/v1/ws", ssl=ctx, subprotocols=["moody.v1"]) as ws:
            await ws.send(json.dumps({"type": "hello", "fw": "0.2.0"}))
            assert "ota" not in json.loads(await ws.recv())  # up to date: no offer, never downgrade
        async with httpx.AsyncClient(verify=ctx) as client:
            r = await client.get(f"https://localhost:{port}/v1/firmware/moody_edge.bin")
        assert r.status_code == 200 and len(r.content) == 1024
    finally:
        server.close()
