"""Minimal private PKI for Moody (home & small deployments).

    python -m moody.pki init                       # create device-ca and service-ca
    python -m moody.pki service gateway --dns moody.lan --ip 192.168.10.5
    python -m moody.pki sign-csr device.csr --cn moody-a1b2c3
    python -m moody.pki revoke <serial-hex> --devices-file deploy/config/devices.yaml

Design:
* ECDSA P-256 everywhere (hardware-accelerated on ESP32-S3).
* Two independent roots: a device certificate can never authenticate as a service.
* Device private keys are generated **on the device**; we only ever sign CSRs.
* CA keys are written 0600 and can be passphrase-encrypted (MOODY_CA_PASSPHRASE).
  For enterprise use an offline root + step-ca/HSM instead (docs/04-pki-identita.md).
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

DEFAULT_DIR = Path(os.environ.get("MOODY_PKI_DIR", "deploy/pki"))
ORG = os.environ.get("MOODY_PKI_ORG", "Moody")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, ORG),
                      x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _write_key(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    passphrase = os.environ.get("MOODY_CA_PASSPHRASE", "").encode() if path.name == "ca.key" else b""
    enc = (serialization.BestAvailableEncryption(passphrase) if passphrase
           else serialization.NoEncryption())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc))


def _write_cert(path: Path, cert: x509.Certificate) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def load_ca(base: Path, which: str) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    folder = base / which
    passphrase = os.environ.get("MOODY_CA_PASSPHRASE", "").encode() or None
    key = serialization.load_pem_private_key((folder / "ca.key").read_bytes(), password=passphrase)
    cert = x509.load_pem_x509_certificate((folder / "ca.pem").read_bytes())
    return key, cert  # type: ignore[return-value]


def create_ca(base: Path, which: str, days: int = 3650) -> x509.Certificate:
    key = ec.generate_private_key(ec.SECP256R1())
    name = _name(f"Moody {which}")
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - dt.timedelta(minutes=5))
        .not_valid_after(_now() + dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                     content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_agreement=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    _write_key(base / which / "ca.key", key)
    _write_cert(base / which / "ca.pem", cert)
    return cert


def _leaf(ca_key, ca_cert, public_key, cn: str, days: int, *, server: bool,
          dns: list[str] = (), ips: list[str] = ()) -> x509.Certificate:  # noqa: B006
    eku = [ExtendedKeyUsageOID.CLIENT_AUTH] + ([ExtendedKeyUsageOID.SERVER_AUTH] if server else [])
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(cn)).issuer_name(ca_cert.subject)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(_now() - dt.timedelta(minutes=5))
        .not_valid_after(_now() + dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=False, crl_sign=False,
                                     content_commitment=False, key_encipherment=False,
                                     data_encipherment=False, key_agreement=True,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage(eku), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_cert.public_key()), critical=False)
    )
    sans: list[x509.GeneralName] = [x509.DNSName(d) for d in dns]
    sans += [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    if sans:
        builder = builder.add_extension(x509.SubjectAlternativeName(sans), critical=False)
    return builder.sign(ca_key, hashes.SHA256())


def issue_service(base: Path, name: str, dns: list[str], ips: list[str], days: int = 397) -> Path:
    ca_key, ca_cert = load_ca(base, "service-ca")
    key = ec.generate_private_key(ec.SECP256R1())
    cert = _leaf(ca_key, ca_cert, key.public_key(), name, days, server=True,
                 dns=sorted({name, *dns}), ips=ips)
    out = base / "services" / name
    _write_key(out / "tls.key", key)
    _write_cert(out / "tls.pem", cert)
    return out


def sign_device_csr(base: Path, csr_pem: bytes, expected_cn: str | None = None, days: int = 365) -> x509.Certificate:
    csr = x509.load_pem_x509_csr(csr_pem)
    if not csr.is_signature_valid:
        raise ValueError("CSR signature invalid")
    cns = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if len(cns) != 1:
        raise ValueError("CSR must have exactly one CN")
    cn = str(cns[0].value)
    if expected_cn and cn != expected_cn:
        raise ValueError(f"CSR CN {cn!r} does not match expected {expected_cn!r}")
    if not cn.startswith("moody-") or len(cn) > 32:
        raise ValueError("device CN must look like moody-xxxxxx")
    pub = csr.public_key()
    if not isinstance(pub, ec.EllipticCurvePublicKey) or pub.curve.name != "secp256r1":
        raise ValueError("device key must be ECDSA P-256")
    ca_key, ca_cert = load_ca(base, "device-ca")
    cert = _leaf(ca_key, ca_cert, pub, cn, days, server=False)
    with open(base / "issued.csv", "a", encoding="utf-8") as fh:
        fh.write(f"{cert.serial_number:X},{cn},{cert.not_valid_after_utc.isoformat()}\n")
    return cert


def revoke(serial_hex: str, devices_file: Path) -> None:
    import yaml

    data = yaml.safe_load(devices_file.read_text(encoding="utf-8")) or {}
    revoked = {str(s).upper() for s in data.get("revoked_serials") or []}
    revoked.add(serial_hex.upper().lstrip("0"))
    data["revoked_serials"] = sorted(revoked)
    devices_file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="moody.pki", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    s = sub.add_parser("service")
    s.add_argument("name")
    s.add_argument("--dns", action="append", default=[])
    s.add_argument("--ip", action="append", default=[])
    s.add_argument("--days", type=int, default=397)
    c = sub.add_parser("sign-csr")
    c.add_argument("csr", type=Path)
    c.add_argument("--cn")
    c.add_argument("--days", type=int, default=365)
    c.add_argument("--out", type=Path)
    r = sub.add_parser("revoke")
    r.add_argument("serial")
    r.add_argument("--devices-file", type=Path, default=Path("deploy/config/devices.yaml"))
    args = parser.parse_args(argv)

    if args.cmd == "init":
        for which in ("device-ca", "service-ca"):
            if (args.dir / which / "ca.key").exists():
                print(f"{which}: already exists, skipping")
                continue
            cert = create_ca(args.dir, which)
            print(f"{which}: created, valid until {cert.not_valid_after_utc:%Y-%m-%d}")
    elif args.cmd == "service":
        out = issue_service(args.dir, args.name, args.dns, args.ip, args.days)
        print(f"service certificate written to {out}")
    elif args.cmd == "sign-csr":
        cert = sign_device_csr(args.dir, args.csr.read_bytes(), args.cn, args.days)
        pem = cert.public_bytes(serialization.Encoding.PEM)
        if args.out:
            args.out.write_bytes(pem)
        else:
            sys.stdout.write(pem.decode())
        print(f"serial={cert.serial_number:X}", file=sys.stderr)
    elif args.cmd == "revoke":
        revoke(args.serial, args.devices_file)
        print(f"serial {args.serial} added to revoked_serials in {args.devices_file}")


if __name__ == "__main__":
    main()
