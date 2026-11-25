"""Device registry: which certificates may connect, and as whom.

The registry maps a device certificate CN to a *pseudonymous* subject id.
Real identities (name, room) are deliberately NOT stored here: in a care home
they live in the existing care-management system, at home nowhere at all.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Device:
    device_id: str
    subject: str
    enabled: bool = True
    quiet_hours: tuple[dt.time, dt.time] | None = None

    def in_quiet_hours(self, now: dt.time) -> bool:
        if not self.quiet_hours:
            return False
        start, end = self.quiet_hours
        return start <= now < end if start < end else now >= start or now < end


def _parse_quiet(value: str | None) -> tuple[dt.time, dt.time] | None:
    if not value:
        return None
    start, end = (dt.time.fromisoformat(v.strip()) for v in value.split("-", 1))
    return start, end


class DeviceRegistry:
    """Reloads the YAML file when it changes (no restart needed to revoke a device)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._mtime = -1.0
        self._devices: dict[str, Device] = {}
        self._revoked: set[str] = set()

    def _reload(self) -> None:
        mtime = self.path.stat().st_mtime
        if mtime == self._mtime:
            return
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        devices = {}
        for device_id, cfg in (data.get("devices") or {}).items():
            cfg = cfg or {}
            devices[device_id] = Device(
                device_id=device_id,
                subject=str(cfg.get("subject") or device_id),
                enabled=bool(cfg.get("enabled", True)),
                quiet_hours=_parse_quiet(cfg.get("quiet_hours")),
            )
        self._devices = devices
        self._revoked = {str(s).upper().lstrip("0") for s in data.get("revoked_serials") or []}
        self._mtime = mtime

    def authorize(self, common_name: str, serial: str) -> Device:
        self._reload()
        if serial.upper().lstrip("0") in self._revoked:
            raise PermissionError("certificate revoked")
        device = self._devices.get(common_name)
        if device is None:
            raise PermissionError("unknown device")
        if not device.enabled:
            raise PermissionError("device disabled")
        return device
