#!/usr/bin/env python3
"""Smoke-test a running orchestrator with a signed webhook.

    python scripts/smoke.py [base_url]

Checks: /healthz, HMAC acceptance (202), redelivery dedupe (200),
bad-signature rejection (401). Uses GITHUB_WEBHOOK_SECRET from the
environment or ../.env (default: the dev fallback in scripts/dev.sh).
Safe to run against any instance: the event targets a repo that does not
exist ("smoke/smoke") — the claim lookup fails or refuses it, and the
outcome is stamped on the delivery ledger. What this verifies is intake:
signature, queueing, dedupe.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx


def load_secret() -> str:
    if os.environ.get("GITHUB_WEBHOOK_SECRET"):
        return os.environ["GITHUB_WEBHOOK_SECRET"]
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            if line.startswith("GITHUB_WEBHOOK_SECRET="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value
    return "dev-webhook-secret"


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080").rstrip("/")
    secret = load_secret()
    ok = True

    def check(label: str, cond: bool, extra: object = "") -> None:
        nonlocal ok
        print(f"{'  ok  ' if cond else ' FAIL '} {label} {extra if not cond else ''}")
        ok = ok and cond

    r = httpx.get(f"{base}/healthz", timeout=10)
    check("healthz", r.status_code == 200 and r.json().get("status") == "ok", r.text)

    body = json.dumps({"action": "smoke",
                       "repository": {"full_name": "smoke/smoke",
                                      "owner": {"login": "smoke"}, "name": "smoke"}}).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    guid = f"smoke-{uuid.uuid4()}"
    headers = {"x-hub-signature-256": sig, "x-github-event": "issues",
               "x-github-delivery": guid, "content-type": "application/json"}

    r = httpx.post(f"{base}/webhooks/github", content=body, headers=headers, timeout=10)
    check("signed webhook accepted (202, queued)", r.status_code == 202, (r.status_code, r.text))

    r = httpx.post(f"{base}/webhooks/github", content=body, headers=headers, timeout=10)
    check("redelivery deduped (200, not queued)",
          r.status_code == 200 and r.json() == {"queued": False}, (r.status_code, r.text))

    bad = dict(headers, **{"x-hub-signature-256": "sha256=deadbeef",
                           "x-github-delivery": f"smoke-{uuid.uuid4()}"})
    r = httpx.post(f"{base}/webhooks/github", content=body, headers=bad, timeout=10)
    check("bad signature rejected (401)", r.status_code == 401, r.status_code)

    time.sleep(1)  # let the worker pick the delivery up before we call it done
    print("SMOKE OK" if ok else "SMOKE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
