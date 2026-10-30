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
import re
import uuid
from collections.abc import Callable
from typing import Any

from .github_app import RepoPort, parse_json_or_empty
from .ledger import Ledger
from .router import IN_PROGRESS, RepoConfig, expedited_next, is_expedited

log = logging.getLogger("factory-orchestrator.reconcile")

# state label -> the role that should have followed it
PENDING_STEP = {
    "factory:spec-approved": "planner",
    "factory:design-approved": "dispatch",
}
# Labels that start a role when applied. Fast-track / profile issues sit idle
# if GitHub delivered the webhook to the Console and never to this process.
START_LABELS = ("factory:fast-track", "factory:profile")
# An expedited task at factory:ready has no gate left in front of it: the
# marker on its epic already approved the implementation start (FACTORY.md
# §4a). Nobody is going to click, so a missed factory:ready delivery parks it
# for good rather than merely delaying a notification — the one state where a
# lost webhook is silent *and* terminal.
EXPEDITED_READY = "factory:ready"
RELEASE_APPROVED = "factory:release-approved"
DISPATCH_MARK = "<!-- factory-release-dispatched -->"

# -- stalled issues -----------------------------------------------------------
# An issue can sit idle where a role should be working it: a run failed or was
# cut off by a restart, a Claude usage limit stopped it, or an expedited chain
# ended without starting the next stage (expedite applied after the task was
# past factory:ready). No webhook is ever coming for any of these, so the sweep
# restarts the role, at most once per stalled run (the guid names that run).

#: The states each role starts from. A run that failed with its issue still
#: in one of them did not do its job, and a restart is safe.
ROLE_STARTS = {
    "intake": {"factory:intake"},
    "planner": {"factory:spec-approved"},
    "testplanner": {"factory:planned"},
    "architect": {"factory:planned"},
    "dispatch": {"factory:design-approved"},
    "implementer": {"factory:ready"},
    "reviewer": {"factory:in-review"},
    "qa": {"factory:in-test"},
    "release": {"factory:ready-to-ship"},
}
#: Failures a restart may answer, per role and issue, before a human must look.
#: Restarts and usage limits are not the role's fault and do not count.
MAX_RETRIES = 2
RETRY_AFTER = dt.timedelta(minutes=10)
#: An expedited chain starts the next stage within seconds, so an issue idle
#: this long after its last run is a chain that broke, not one still moving.
STALL_AFTER = dt.timedelta(minutes=20)
#: When a usage limit names no reset time this engine can read.
LIMIT_WAIT = dt.timedelta(minutes=30)

INTERRUPTED_MARK = "Interrupted: the orchestrator restarted"
_LIMIT_RE = re.compile(r"You'?ve hit your (?:[\w-]+ )?limit[^\n]*", re.IGNORECASE)
_RESET_RE = re.compile(r"resets\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)\s*\(UTC\)", re.IGNORECASE)
LIMIT_MARK = "Claude usage limit reached"


def usage_limit_error(transcript: str | None) -> str | None:
    """The failure reason for a run Claude's usage limit stopped, or None."""
    m = _LIMIT_RE.search(transcript or "")
    if not m:
        return None
    return (f"{LIMIT_MARK}: \"{m.group(0).strip()}\". The run stopped early. "
            "The factory starts this role again on its own once the limit resets.")


def limit_resets_at(error: str, finished: dt.datetime) -> dt.datetime:
    """When the limit in `error` resets: its UTC clock time after `finished`."""
    m = _RESET_RE.search(error or "")
    if not m:
        return finished + LIMIT_WAIT
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
    at = finished.replace(hour=hour, minute=int(m.group(2) or 0), second=0, microsecond=0)
    return at if at > finished else at + dt.timedelta(days=1)


def _when(v: Any) -> dt.datetime | None:
    if v is None:
        return None
    if isinstance(v, str):
        v = dt.datetime.fromisoformat(v)
    return v if v.tzinfo else v.replace(tzinfo=dt.UTC)


def _kind(run: dict[str, Any]) -> str:
    """success | interrupted | limit | failed | other, for one finished run."""
    outcome, error = run.get("outcome"), run.get("error") or ""
    if outcome == "success":
        return "success"
    if outcome not in ("error", "timeout"):
        return "other"  # no_op: the role chose to change nothing
    if INTERRUPTED_MARK in error:
        return "interrupted"
    if LIMIT_MARK in error or _LIMIT_RE.search(error):
        return "limit"
    return "failed"


def stalled_role(port: RepoPort, issue: dict[str, Any], labels: list[str],
                 runs: list[dict[str, Any]], epics: bool,
                 port_for: Callable[[str, str], RepoPort] | None,
                 now: dt.datetime) -> tuple[str, str] | None:
    """(role, state) to restart on an idle issue, or None. `runs` newest first."""
    if not runs or IN_PROGRESS in labels or "factory:blocked" in labels:
        return None
    if any(r.get("finished_at") is None for r in runs):
        return None  # a run is live
    states = [x for x in labels if x.startswith("factory:") and x not in (
        IN_PROGRESS, "factory:expedite", "factory:blocked")]
    if len(states) != 1:
        return None  # no state, or drift: a human's call
    state, last = states[0], runs[0]
    finished = _when(last.get("finished_at")) or now
    kind = _kind(last)

    if kind in ("interrupted", "limit", "failed") and state in ROLE_STARTS.get(last["role"], ()):
        if kind == "limit" and now < limit_resets_at(last.get("error") or "", finished):
            return None
        # After a restart the event that started the run is replayed first;
        # the grace lets it go ahead, so the restart only fills a real gap.
        if kind != "limit" and now - finished < RETRY_AFTER:
            return None
        if kind == "failed":
            fails = 0
            for r in runs:
                if r["role"] != last["role"] or _kind(r) == "success":
                    break
                fails += _kind(r) == "failed"
            if fails > MAX_RETRIES:
                return None
        return last["role"], state

    nxt = expedited_next(state, epics)
    if (nxt and not nxt.startswith("gate:") and now - finished >= STALL_AFTER
            and is_expedited(port, issue, port_for)):
        return nxt, state
    return None


def _queue_restart(ledger: Ledger, port: RepoPort, n: int, role: str, state: str,
                   run_id: str) -> int:
    payload = {
        "inputs": {"role": role, "issue_number": n, "expect_state": state},
        "sender": {"login": "factory-reconciler"},
        "repository": {"full_name": f"{port.owner}/{port.repo}",
                       "owner": {"login": port.owner}, "name": port.repo},
    }
    # Keyed on the run that left the issue idle, so every pass of the sweep
    # queues it once. A newer run, failed or not, is a new key.
    fresh = ledger.record_delivery(f"restart-{run_id}", "workflow_dispatch", payload)
    if fresh:
        log.info("queued %s restart on %s/%s#%s (idle at %s after run %s)",
                 role, port.owner, port.repo, n, state, run_id)
    return 1 if fresh else 0


def sweep_repo(port: RepoPort, ledger: Ledger,
               port_for: Callable[[str, str], RepoPort] | None = None) -> int:
    """Queue synthetic events for missed steps; returns how many were queued.

    `port_for` opens a port on any repo this engine is installed on. Only the
    expedite check needs it, and only for a cross-repo epic (FACTORY.md §7):
    a task in a sibling repo carries no marker of its own, so deciding whether
    it is expedited means reading an epic in another repo. Without it that
    read cannot happen and the task reads as un-expedited — which for every
    other sweep would be harmless, but here means the one state where a lost
    delivery is silent *and* terminal never gets swept at all.
    """
    queued = 0
    full = f"{port.owner}/{port.repo}"
    epics = RepoConfig(branches=parse_json_or_empty(
        port.get_file(".github/factory-branches.json"))).epics
    now = dt.datetime.now(dt.UTC)
    for issue in port.list_issues(state="open"):
        if issue.get("pull_request") is not None:
            continue
        labels = [(l if isinstance(l, str) else l.get("name"))
                  for l in issue.get("labels", [])]
        n = issue["number"]
        runs = ledger.list_runs(repo=full, issue=n, limit=20)

        stalled = stalled_role(port, issue, labels, runs, epics, port_for, now)
        if stalled:
            queued += _queue_restart(ledger, port, n, *stalled, run_id=runs[0]["id"])
        elif not runs:
            for label, _role in PENDING_STEP.items():
                if label in labels:
                    queued += _queue_labeled(ledger, port, issue, label)
                    break
            else:
                for label in START_LABELS:
                    if label in labels:
                        queued += _queue_labeled(ledger, port, issue, label)
                        break
                else:
                    # Last, because it is the only one that has to read the
                    # epic to decide: an unexpedited factory:ready is waiting
                    # on a human by design and must never be swept.
                    if (EXPEDITED_READY in labels and IN_PROGRESS not in labels
                            and "factory:blocked" not in labels
                            and is_expedited(port, issue, port_for)):
                        queued += _queue_labeled(ledger, port, issue, EXPEDITED_READY)

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
