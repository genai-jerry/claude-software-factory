"""Put a fast-lane fix on staging once it is green (FACTORY.md §5).

The fast lane opens one PR onto the integration branch and used to stop there,
leaving a person to merge it — and an unmerged fix sat for hours (beacon-api#379).
Merging onto the integration branch is not shipping: production still waits for
the human merge of the promotion PR (gate G3). So the orchestrator merges the
fast-lane PR itself, right after the run and on every reconciler sweep, when:

- the repo has not turned it off (`"fast_track_merge": false` in
  `.github/factory-release.json`);
- the PR is the fast lane's own (`factory/<n>-…`, closing the issue) and is based
  on the integration branch — never the default branch;
- GitHub says it merges cleanly, and no check or status on it has failed or is
  still running.

A PR that conflicts or fails is said once on the issue and left for a person.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .github_app import RepoPort

log = logging.getLogger("factory-orchestrator.fast-track-merge")

FAST_TRACK = "factory:fast-track"
MERGED_MARK = "<!-- factory-fast-track-merged -->"
HELD_MARK = "<!-- factory-fast-track-held -->"
CLOSED_MARK = "<!-- factory-fast-track-closed -->"


def enabled(release_cfg: dict[str, Any]) -> bool:
    return release_cfg.get("fast_track_merge", True) is not False


def fast_track_pr(port: RepoPort, number: int) -> dict[str, Any] | None:
    """The open PR the fast lane opened for this issue, if any."""
    closes = re.compile(rf"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#{number}\b", re.IGNORECASE)
    for pr in port.list_pulls():
        head = (pr.get("head") or {}).get("ref", "")
        if head.startswith(f"factory/{number}-") and closes.search(pr.get("body") or ""):
            return pr
    return None


def merged_fast_track_pr(port: RepoPort, number: int) -> dict[str, Any] | None:
    """The fast lane's PR for this issue, once it has been merged (by the factory or a person)."""
    closes = re.compile(rf"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#{number}\b", re.IGNORECASE)
    try:
        closed = port.list_closed_pulls()
    except Exception:  # noqa: BLE001 - not finding it is "not yet", never a failed sweep
        return None
    for pr in closed:
        head = (pr.get("head") or {}).get("ref", "")
        if pr.get("merged_at") and head.startswith(f"factory/{number}-") and closes.search(pr.get("body") or ""):
            return pr
    return None


def close_if_merged(port: RepoPort, number: int) -> bool:
    """Close a fast-lane issue whose fix is on the integration branch.

    GitHub closes an issue only when its PR merges into the DEFAULT branch, and this
    lane's PR goes onto the integration branch, so without this the issue stayed open
    until some promotion happened to name it — and Compass listed it as work in
    progress long after the fix was on staging (beacon-web#56, #74).
    """
    pr = merged_fast_track_pr(port, number)
    if pr is None:
        return False
    base = (pr.get("base") or {}).get("ref", "the integration branch")
    port.update_issue_state(number, "closed")  # type: ignore[attr-defined]
    port.create_comment(number, (
        f"**Done: the fix is on `{base}`** (#{pr['number']}). Closing this issue.\n\n"
        "**You need to:** nothing. It reaches production with the next promotion PR, "
        "which a person merges (gate G3).\n\n"
        f"{CLOSED_MARK}\n<!-- factory-agent -->"))
    return True


def _said(port: RepoPort, number: int, mark: str) -> bool:
    try:
        return any(mark in (c.get("body") or "") for c in port.list_comments(number))
    except Exception:  # noqa: BLE001 - a failed read means "say it", never "merge twice"
        return False


def merge_fast_track(port: RepoPort, number: int, release_cfg: dict[str, Any]) -> str:
    """Try to merge this fast-lane issue's PR. Returns what happened, in a word:
    `merged` (the issue is closed too), `closed` (it was already merged: the issue
    is closed now), `waiting` (checks running / GitHub still computing), `held`
    (conflict or failure, said on the issue), `off`, or `none` (no PR)."""
    pr = fast_track_pr(port, number)
    if pr is None:
        # No open PR: its fix may already be on the integration branch (merged by the
        # factory earlier, or by a person) with the issue still open.
        return "closed" if close_if_merged(port, number) else "none"
    if not enabled(release_cfg):
        return "off"
    n_pr = pr["number"]
    base = (pr.get("base") or {}).get("ref", "")
    if not base or base == port.default_branch():
        log.warning("fast-track PR #%s on %s/%s is based on %r - not merging onto the default branch",
                    n_pr, port.owner, port.repo, base)
        return "held"
    state = port.pr_merge_state(n_pr)
    if state.get("failing"):
        why = "a check on it failed"
    elif state.get("mergeable") is False:
        why = "it no longer merges cleanly onto " + f"`{base}`"
    elif state.get("pending") or state.get("mergeable") is None:
        return "waiting"
    else:
        try:
            port.merge_pr(n_pr, "squash")
        except Exception as e:  # noqa: BLE001 - GitHub refusing is a reason to tell a person, not a crash
            why = f"GitHub refused the merge ({e})"
        else:
            log.info("merged fast-track PR #%s onto %s in %s/%s", n_pr, base, port.owner, port.repo)
            if not _said(port, number, MERGED_MARK):
                port.create_comment(number, (
                    f"**Done: the fix is on `{base}`.** The factory merged #{n_pr} there once it was green, "
                    "and is closing this issue.\n\n"
                    "**You need to:** nothing. It reaches production with the next promotion PR, "
                    "which a person merges (gate G3).\n\n"
                    f"{MERGED_MARK}\n<!-- factory-agent -->"))
            port.update_issue_state(number, "closed")  # type: ignore[attr-defined]
            return "merged"
    if not _said(port, number, HELD_MARK):
        port.create_comment(number, (
            f"**The fix was not merged onto `{base}`: {why}.**\n\n"
            f"**You need to:** look at #{n_pr} — fix it there or merge it yourself. "
            "The factory does not merge a red or conflicting PR.\n\n"
            f"{HELD_MARK}\n<!-- factory-agent -->"))
    return "held"
