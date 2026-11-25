"""Simulates the firmware side of the USB provisioning protocol."""

import base64
import importlib.util
import queue
from pathlib import Path

from conftest import make_csr
from cryptography import x509

spec = importlib.util.spec_from_file_location(
    "provision", Path(__file__).resolve().parents[2] / "firmware" / "tools" / "provision.py")
provision_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision_mod)


class FakeDevice:
    """Behaves like firmware/main/provision.c, including interleaved log lines."""

    def __init__(self, device_id="moody-c0ffee"):
        self.device_id = device_id
        self.out = queue.Queue()
        self.store = {}
        self.committed = False

    def write(self, data):
        cmd = data.decode().strip()
        self.out.put(b"I (1234) wifi: some log line\n")
        if cmd == "ID":
            self.out.put(f"OK ID {self.device_id} 0.1.0\n".encode())
        elif cmd == "GENKEY":
            csr, key = make_csr(self.device_id)
            self.store["key"] = key
            self.out.put(b"OK CSR " + base64.b64encode(csr) + b"\n")
        elif cmd.startswith("SET "):
            _, k, v = cmd.split(" ", 2)
            self.store[k] = base64.b64decode(v).decode()
            self.out.put(b"OK\n")
        elif cmd == "COMMIT":
            self.committed = True
            self.out.put(b"OK COMMIT\n")

    def flush(self):
        pass

    def readline(self):
        try:
            return self.out.get(timeout=0.5)
        except queue.Empty:
            return b""


def test_provision_happy_path(pki_dir, tmp_path):
    dev = FakeDevice()
    device_id, serial = provision_mod.provision(
        provision_mod.Provisioner(dev, timeout=2), pki_dir=pki_dir, ssid="Moody-IoT", password="s3cret",
        gateway="wss://moody.lan:8443/v1/ws")
    assert device_id == "moody-c0ffee" and dev.committed
    cert = x509.load_pem_x509_certificate(dev.store["cert"].encode())
    assert cert.subject.rfc4514_string().endswith("CN=moody-c0ffee") or "moody-c0ffee" in cert.subject.rfc4514_string()
    assert f"{cert.serial_number:X}" == serial
    assert dev.store["ca"] == (pki_dir / "service-ca" / "ca.pem").read_text()
    assert dev.store["uri"].startswith("wss://") and dev.store["pass"] == "s3cret"
    devices = tmp_path / "devices.yaml"
    provision_mod.register(devices, device_id, "res-007")
    assert "res-007" in devices.read_text()


def test_plain_ws_refused(pki_dir):
    import pytest
    with pytest.raises(provision_mod.ProvisioningError):
        provision_mod.provision(provision_mod.Provisioner(FakeDevice(), timeout=1), pki_dir=pki_dir,
                                ssid="x", password="y", gateway="ws://moody.lan:8443")
