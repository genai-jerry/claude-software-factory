"""Reconciliation: catch automatic steps that were missed while offline.

Webhook delivery is not guaranteed (the service may be down past GitHub's
redelivery window). The sweep runs at startup and on a timer, looking only
for states that imply a *pending automatic step* — an approved gate whose
follow-up role never ran, an approved release never fanned out — and
re-queues a synthetic event through the same idempotent path as a real
delivery. Router idempotence (dispatch receipts, said-once markers) and the
run ledger make a sweep that finds nothing cost nothing.
"""

from __future__ import annotations

import logging
import uuid

from .github_app import RepoPort
from .ledger import Ledger

log = logging.getLogger("factory-orchestrator.reconcile")

# state label -> the role that should have followed it
PENDING_STEP = {
    "factory:spec-approved": "planner",
    "factory:design-approved": "dispatch",
}
# Labels that start a role when applied. Fast-track / profile issues sit idle
# if GitHub delivered the webhook to the Console and never to this process.
START_LABELS = ("factory:fast-track", "factory:profile")
RELEASE_APPROVED = "factory:release-approved"
DISPATCH_MARK = "<!-- factory-release-dispatched -->"


def sweep_repo(port: RepoPort, ledger: Ledger) -> int:
    """Queue synthetic events for missed steps; returns how many were queued."""
    queued = 0
    full = f"{port.owner}/{port.repo}"
    for issue in port.list_issues(state="open"):
        if issue.get("pull_request") is not None:
            continue
        labels = [(l if isinstance(l, str) else l.get("name"))
                  for l in issue.get("labels", [])]
        n = issue["number"]

        if not ledger.list_runs(repo=full, issue=n):
            for label, _role in PENDING_STEP.items():
                if label in labels:
                    queued += _queue_labeled(ledger, port, issue, label)
                    break
            else:
                for label in START_LABELS:
                    if label in labels:
                        queued += _queue_labeled(ledger, port, issue, label)
                        break

        if RELEASE_APPROVED in labels and "factory:release" in labels:
            comments = port.list_comments(n)
            if not any(DISPATCH_MARK in (c.get("body") or "") for c in comments):
                queued += _queue_labeled(ledger, port, issue, RELEASE_APPROVED)
    if queued:
        log.info("reconcile %s: queued %d missed step(s)", full, queued)
    return queued


def _queue_labeled(ledger: Ledger, port: RepoPort, issue: dict, label: str) -> int:
    payload = {
        "action": "labeled",
        "issue": issue,
        "label": {"name": label},
        "sender": {"login": "factory-reconciler"},
        "repository": {"full_name": f"{port.owner}/{port.repo}",
                       "owner": {"login": port.owner}, "name": port.repo},
    }
    # A deterministic guid per (issue, label, current label set) would suppress
    # legitimate re-sweeps after state moved on; a fresh guid is safe because
    # the router itself is idempotent for these events.
    fresh = ledger.record_delivery(f"reconcile-{uuid.uuid4()}", "issues", payload)
    return 1 if fresh else 0
