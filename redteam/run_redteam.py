#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) Moody contributors
"""Moody red-team harness: replays adversarial cases against the brain ``/v1/turn`` API.

The brain only accepts mTLS clients with a certificate signed by the *service* CA,
so run this with a service certificate (e.g. the gateway's) from a host or
container that can reach the brain. See docs/11-red-teaming.md.

    python redteam/run_redteam.py \
        --brain-url https://brain:8080 \
        --cert deploy/pki/services/gateway/tls.pem --key deploy/pki/services/gateway/tls.key \
        --ca deploy/pki/service-ca/ca.pem --cases redteam/cases.yaml
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml


@dataclass
class CaseResult:
    id: str
    category: str
    passed: bool
    reply: str = ""
    reply_category: str = ""
    failures: list[str] = field(default_factory=list)
    latency_ms: int = 0


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases = data.get("cases", data) if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError("cases file must contain a list (or a 'cases:' list)")
    return cases


def evaluate(case: dict[str, Any], response: dict[str, Any]) -> list[str]:
    """Return a list of human-readable failures (empty list = pass)."""
    expect = case.get("expect") or {}
    reply = str(response.get("reply", ""))
    low = reply.lower()
    failures: list[str] = []
    want_cat = expect.get("category")
    if want_cat and response.get("category") != want_cat:
        failures.append(f"category {response.get('category')!r} != {want_cat!r}")
    for needle in expect.get("not_contains") or []:
        if str(needle).lower() in low:
            failures.append(f"reply contains forbidden {needle!r}")
    any_of = expect.get("contains_any") or []
    if any_of and not any(str(n).lower() in low for n in any_of):
        failures.append(f"reply contains none of {any_of!r}")
    return failures


def ssl_context(cert: Path, key: Path, ca: Path) -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(str(cert), str(key))
    return ctx


def run(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    client = httpx.Client(verify=ssl_context(args.cert, args.key, args.ca), timeout=args.timeout)
    results: list[CaseResult] = []
    for case in cases:
        # one session per case: no conversational state leaks between tests
        session_id = f"rt-{uuid.uuid4().hex[:12]}"
        turns = case.get("setup_turns") or []
        started = time.monotonic()
        try:
            for turn in turns:
                client.post(f"{args.brain_url}/v1/turn",
                            json={"subject": args.subject, "session_id": session_id, "text": turn})
            resp = client.post(f"{args.brain_url}/v1/turn",
                               json={"subject": args.subject, "session_id": session_id, "text": case["input"]})
            resp.raise_for_status()
            body = resp.json()
            failures = evaluate(case, body)
        except Exception as exc:  # noqa: BLE001 - report and continue with the next case
            body, failures = {}, [f"request failed: {type(exc).__name__}: {exc}"]
        results.append(CaseResult(
            id=str(case.get("id")), category=str(case.get("category", "")), passed=not failures,
            reply=str(body.get("reply", "")), reply_category=str(body.get("category", "")),
            failures=failures, latency_ms=int((time.monotonic() - started) * 1000),
        ))

    width = max((len(r.id) for r in results), default=4)
    print(f"{'ID':<{width}}  {'RESULT':<6}  {'CATEGORY':<20}  DETAILS")
    for r in results:
        detail = "; ".join(r.failures) if r.failures else f"{r.latency_ms} ms"
        print(f"{r.id:<{width}}  {'PASS' if r.passed else 'FAIL':<6}  {r.category:<20}  {detail}")
    failed = [r for r in results if not r.passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "brain_url": args.brain_url, "subject": args.subject,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "passed": len(results) - len(failed), "total": len(results),
        "results": [asdict(r) for r in results],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report written to {args.out}")
    return 1 if failed else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Moody red-team harness (brain /v1/turn over mTLS)")
    p.add_argument("--brain-url", default="https://localhost:8080")
    p.add_argument("--cert", type=Path, default=Path("deploy/pki/services/gateway/tls.pem"),
                   help="service client certificate (signed by service-ca)")
    p.add_argument("--key", type=Path, default=Path("deploy/pki/services/gateway/tls.key"))
    p.add_argument("--ca", type=Path, default=Path("deploy/pki/service-ca/ca.pem"), help="service CA")
    p.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.yaml"))
    p.add_argument("--subject", default="redteam-001",
                   help="pseudonym used for the tests (use a dedicated one, never a real resident)")
    p.add_argument("--out", type=Path, default=Path("redteam/results/report.json"))
    p.add_argument("--timeout", type=float, default=120)
    args = p.parse_args(argv)
    args.brain_url = args.brain_url.rstrip("/")
    return args


if __name__ == "__main__":
    sys.exit(run(parse_args()))
