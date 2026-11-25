"""TLS helpers: every Moody hop is mutually authenticated (mTLS).

Two independent private CAs are used (see scripts/pki.py):

* ``device-ca``  signs edge device client certificates. Only the gateway trusts it.
* ``service-ca`` signs service certificates (gateway, brain, wellbeing). Devices
  trust it to authenticate the gateway; services trust it to authenticate each other.

Keeping the CAs separate means a stolen device certificate can never be used
to talk to the brain or to the tools directly.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from pathlib import Path

# Device-facing ciphers: ECDHE + AEAD only (ESP32 mbedTLS supports these with HW acceleration).
_TLS12_CIPHERS = "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305"


@dataclass(frozen=True)
class TLSFiles:
    cert: Path
    key: Path
    ca: Path


def server_context(files: TLSFiles, *, allow_tls12: bool = False) -> ssl.SSLContext:
    """Server context that *requires* a client certificate signed by ``files.ca``."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2 if allow_tls12 else ssl.TLSVersion.TLSv1_3
    if allow_tls12:
        ctx.set_ciphers(_TLS12_CIPHERS)
    ctx.options |= ssl.OP_NO_COMPRESSION | ssl.OP_NO_RENEGOTIATION
    ctx.load_cert_chain(str(files.cert), str(files.key))
    ctx.load_verify_locations(cafile=str(files.ca))
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def client_context(files: TLSFiles) -> ssl.SSLContext:
    """Client context presenting our certificate and pinning the peer to ``files.ca``."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(str(files.cert), str(files.key))
    ctx.load_verify_locations(cafile=str(files.ca))
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def peer_identity(peercert: dict | None) -> tuple[str, str]:
    """Return ``(common_name, serial_hex)`` from ``SSLSocket.getpeercert()`` output."""
    if not peercert:
        raise PermissionError("no client certificate")
    cn = ""
    for rdn in peercert.get("subject", ()):
        for key, value in rdn:
            if key == "commonName":
                cn = value
    serial = str(peercert.get("serialNumber", "")).upper().lstrip("0")
    if not cn:
        raise PermissionError("client certificate has no CN")
    return cn, serial
