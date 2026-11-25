from __future__ import annotations

from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from moody import pki


def make_csr(cn: str, key=None) -> tuple[bytes, ec.EllipticCurvePrivateKey]:
    key = key or ec.generate_private_key(ec.SECP256R1())
    csr = (x509.CertificateSigningRequestBuilder()
           .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
           .sign(key, hashes.SHA256()))
    return csr.public_bytes(serialization.Encoding.PEM), key


@pytest.fixture()
def pki_dir(tmp_path: Path) -> Path:
    base = tmp_path / "pki"
    pki.create_ca(base, "device-ca")
    pki.create_ca(base, "service-ca")
    pki.issue_service(base, "gateway", dns=["localhost"], ips=["127.0.0.1"])
    return base


@pytest.fixture()
def device_cert(pki_dir: Path):
    """Return (cert_path, key_path, serial_hex) for device moody-test01."""
    def _make(cn: str = "moody-test01"):
        csr, key = make_csr(cn)
        cert = pki.sign_device_csr(pki_dir, csr, cn)
        folder = pki_dir / "devices" / cn
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "tls.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (folder / "tls.key").write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                                           serialization.PrivateFormat.PKCS8,
                                                           serialization.NoEncryption()))
        return folder / "tls.pem", folder / "tls.key", f"{cert.serial_number:X}"
    return _make
