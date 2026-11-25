"""Gateway entrypoint."""

from __future__ import annotations

import asyncio
import logging
import ssl
from pathlib import Path

from ..common.config import env, env_int, read_secret
from ..common.logging import setup_logging
from ..common.tls import TLSFiles, client_context, server_context
from .brain_client import BrainClient, TokenProvider
from .devices import DeviceRegistry
from .server import Gateway, GatewaySettings
from .speech import WyomingSTT, WyomingTTS

log = logging.getLogger("moody.gateway")


def main() -> None:
    setup_logging(env("MOODY_LOG_LEVEL", "INFO"))
    cert, key = Path(env("MOODY_TLS_CERT", required=True)), Path(env("MOODY_TLS_KEY", required=True))
    # Devices are verified against the *device* CA; the brain against the *service* CA.
    device_side = server_context(TLSFiles(cert, key, Path(env("MOODY_DEVICE_CA", required=True))),
                                 allow_tls12=True)
    service_side = client_context(TLSFiles(cert, key, Path(env("MOODY_TLS_CA", required=True))))

    tokens = None
    if env("MOODY_OIDC_TOKEN_URL"):
        tokens = TokenProvider(env("MOODY_OIDC_TOKEN_URL"), env("MOODY_OIDC_CLIENT_ID", "moody-gateway"),
                               read_secret("MOODY_OIDC_CLIENT_SECRET"),
                               verify=ssl.create_default_context(cafile=env("MOODY_TLS_CA")))

    gateway = Gateway(
        registry=DeviceRegistry(env("MOODY_DEVICES_FILE", "/config/devices.yaml")),
        stt=WyomingSTT(env("MOODY_STT_HOST", "whisper"), env_int("MOODY_STT_PORT", 10300),
                       env("MOODY_LOCALE", "it")),
        tts=WyomingTTS(env("MOODY_TTS_HOST", "piper"), env_int("MOODY_TTS_PORT", 10200),
                       env("MOODY_TTS_VOICE", "it_IT-paola-medium")),
        brain=BrainClient(env("MOODY_BRAIN_URL", "https://brain:8080"), service_side, tokens),
        ssl_context=device_side,
        settings=GatewaySettings(port=env_int("MOODY_GATEWAY_PORT", 8443), tz=env("TZ", "Europe/Rome"),
                                 firmware_dir=Path(env("MOODY_FIRMWARE_DIR")) if env("MOODY_FIRMWARE_DIR") else None),
    )

    async def run() -> None:
        async with gateway.serve():
            log.info("gateway listening", extra={"fields": {"port": gateway.settings.port}})
            await asyncio.Future()

    asyncio.run(run())


if __name__ == "__main__":
    main()
