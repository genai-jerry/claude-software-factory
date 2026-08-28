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

import datetime as dt
import logging
import uuid

from .github_app import RepoPort
from .guards import clear_in_progress, report_failure
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


def reap_stale_runs(port: RepoPort, ledger: Ledger, run_timeout_seconds: int,
                    public_base_url: str) -> int:
    """Close out runs whose process died, and free the issues they pinned.

    `execute_role` finishes every run and clears `factory:in-progress` in a
    `finally`, so the only way a row stays open past the role timeout is that
    the process never got there — a restart, an OOM, a lost container. What it
    leaves behind is worse than a failure: the run reads as live forever, the
    marker makes the router treat the issue as in flight (so relabelling it
    `factory:fast-track` does nothing), and the sweep below skips any issue
    that has a recorded run. Nothing self-heals until the row is terminal.

    Grace is a full extra timeout on top of the cap, so a run this reaps is
    unambiguously dead rather than merely slow.
    """
    reaped = 0
    full = f"{port.owner}/{port.repo}"
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=run_timeout_seconds * 2)
    for run in ledger.list_unfinished_runs(repo=full, older_than=cutoff):
        role, issue_n = run["role"], run["issue"]
        started = run["started_at"]
        reason = (
            f"The {role} run was recorded as started at {started} and never reported an "
            "outcome — the orchestrator process did not survive it. Nothing was left "
            "running; the run log holds whatever it managed to write. Any work it had "
            "already pushed to GitHub still stands, so check this thread and any PR it "
            "links before starting the role again."
        )
        ledger.finish_run(run["id"], outcome="error", model=run.get("model"),
                          transcript_path=run.get("transcript_path"), error=reason)
        report_failure(port, issue_n, role, f"{public_base_url}/runs/{run['id']}", reason=reason)
        clear_in_progress(port, issue_n)
        log.warning("reaped stale %s run %s on %s#%s", role, run["id"], full, issue_n)
        reaped += 1
    return reaped


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
