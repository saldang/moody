#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Provision a Moody device over USB.

The device generates its own ECDSA P-256 key and returns a CSR: the private key
never leaves the device. We sign the CSR with the *device CA*, then send the
Wi-Fi credentials, the gateway URL and the *service CA* (used by the device to
authenticate the gateway).

    .venv/bin/python firmware/tools/provision.py --port /dev/ttyACM0 \
        --ssid Moody-IoT --gateway wss://moody.lan:8443/v1/ws --subject res-001

Requires: pip install -e "server[pki]"  (cryptography, pyserial, pyyaml)
"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))

from cryptography.hazmat.primitives import serialization  # noqa: E402

from moody import pki  # noqa: E402


class ProvisioningError(RuntimeError):
    pass


class Provisioner:
    """Speaks the line protocol implemented in firmware/main/provision.c."""

    def __init__(self, port, timeout: float = 20.0) -> None:  # port: pyserial-like object
        self.port = port
        self.timeout = timeout

    def _send(self, line: str) -> None:
        self.port.write((line + "\n").encode())
        self.port.flush()

    def _expect(self, prefix: str = "OK") -> str:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            raw = self.port.readline()
            if not raw:
                continue
            line = raw.decode(errors="replace").strip()
            if line.startswith("ERR"):
                raise ProvisioningError(line)
            if line.startswith(prefix):
                return line
            # anything else is device log output: ignore
        raise ProvisioningError(f"timeout waiting for {prefix!r}")

    def hello(self) -> tuple[str, str]:
        for _ in range(15):
            self._send("ID")
            try:
                parts = self._expect("OK ID").split()
                return parts[2], parts[3]
            except ProvisioningError:
                continue
        raise ProvisioningError("device not in provisioning mode (factory reset it first)")

    def generate_csr(self) -> bytes:
        self._send("GENKEY")
        return base64.b64decode(self._expect("OK CSR").split(" ", 2)[2])

    def set(self, key: str, value: str) -> None:
        self._send(f"SET {key} {base64.b64encode(value.encode()).decode()}")
        self._expect("OK")

    def commit(self) -> None:
        self._send("COMMIT")
        self._expect("OK COMMIT")


def provision(prov: Provisioner, *, pki_dir: Path, ssid: str, password: str, gateway: str,
              ntp: str | None = None, days: int = 365) -> tuple[str, str]:
    if not gateway.startswith("wss://"):
        raise ProvisioningError("gateway must be a wss:// URL (TLS is mandatory)")
    device_id, fw = prov.hello()
    print(f"device {device_id} (firmware {fw})")
    csr = prov.generate_csr()
    cert = pki.sign_device_csr(pki_dir, csr, expected_cn=device_id, days=days)
    serial = f"{cert.serial_number:X}"
    prov.set("cert", cert.public_bytes(serialization.Encoding.PEM).decode())
    prov.set("ca", (pki_dir / "service-ca" / "ca.pem").read_text())
    prov.set("ssid", ssid)
    prov.set("pass", password)
    prov.set("uri", gateway)
    if ntp:
        prov.set("ntp", ntp)
    prov.commit()
    return device_id, serial


def register(devices_file: Path, device_id: str, subject: str) -> None:
    import yaml

    data = yaml.safe_load(devices_file.read_text(encoding="utf-8")) if devices_file.exists() else {}
    data = data or {}
    data.setdefault("devices", {})
    data["devices"][device_id] = {"subject": subject, "enabled": True, "quiet_hours": "22:00-07:30"}
    data.setdefault("revoked_serials", [])
    devices_file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True, help="e.g. /dev/ttyACM0, COM5")
    ap.add_argument("--ssid", required=True)
    ap.add_argument("--gateway", required=True, help="wss://moody.lan:8443/v1/ws")
    ap.add_argument("--ntp", help="NTP server reachable from the IoT network (default: DHCP / pool.ntp.org)")
    ap.add_argument("--pki", type=Path, default=ROOT / "deploy" / "pki")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--subject", help="pseudonym to register in devices.yaml (e.g. res-001), never a name")
    ap.add_argument("--devices-file", type=Path, default=ROOT / "deploy" / "config" / "devices.yaml")
    args = ap.parse_args()

    password = os.environ.get("MOODY_WIFI_PASSWORD") or getpass.getpass("Wi-Fi password: ")
    import serial  # pyserial

    port = serial.Serial()
    port.port, port.baudrate, port.timeout = args.port, 115200, 1
    port.dtr = port.rts = False  # do not reset the chip when opening the port
    port.open()
    try:
        device_id, serial_hex = provision(Provisioner(port), pki_dir=args.pki, ssid=args.ssid, password=password,
                                          gateway=args.gateway, ntp=args.ntp, days=args.days)
    finally:
        port.close()
    print(f"provisioned {device_id}, certificate serial {serial_hex}")
    if args.subject:
        register(args.devices_file, device_id, args.subject)
        print(f"registered in {args.devices_file} as {args.subject} (gateway reloads it automatically)")
    else:
        print(f"add it to devices.yaml:\n  {device_id}:\n    subject: res-XXX\n    enabled: true")


if __name__ == "__main__":
    main()
