"""Run the wellbeing MCP server over Streamable HTTP with mandatory mTLS."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl
from pathlib import Path

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings

from ..common.config import env, env_int, read_secret
from ..common.logging import setup_logging
from .server import build_server
from .store import WellbeingStore

log = logging.getLogger("moody.wellbeing")


def main() -> None:
    setup_logging(env("MOODY_LOG_LEVEL", "INFO"))
    data_dir = Path(env("MOODY_DATA_DIR", "/data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    store = WellbeingStore(
        data_dir / "wellbeing.sqlite3",
        key=read_secret("MOODY_DATA_KEY"),
        retention_days=env_int("MOODY_RETENTION_DAYS", 30),
    )
    mcp = build_server(
        store,
        tz=env("TZ", "Europe/Rome"),
        ntfy_url=env("MOODY_NTFY_URL"),
        ntfy_topic=env("MOODY_NTFY_TOPIC"),
        ntfy_token=read_secret("MOODY_NTFY_TOKEN", ""),
    )
    host_name = env("MOODY_WELLBEING_HOSTNAME", "wellbeing")
    port = env_int("MOODY_WELLBEING_PORT", 8090)
    app = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[f"{host_name}:{port}"],
            allowed_origins=[],
        ),
    )

    async def purge_loop() -> None:
        while True:
            with contextlib.suppress(Exception):
                n = store.purge_expired()
                if n:
                    log.info("retention purge", extra={"fields": {"rows": n}})
            await asyncio.sleep(3600)

    config = uvicorn.Config(
        app,
        host="0.0.0.0",  # noqa: S104 - container-internal network only
        port=port,
        ssl_certfile=env("MOODY_TLS_CERT", required=True),
        ssl_keyfile=env("MOODY_TLS_KEY", required=True),
        ssl_ca_certs=env("MOODY_TLS_CA", required=True),
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        log_config=None,
        server_header=False,
    )

    async def run() -> None:
        task = asyncio.create_task(purge_loop())
        try:
            await uvicorn.Server(config).serve()
        finally:
            task.cancel()

    asyncio.run(run())


if __name__ == "__main__":
    main()
