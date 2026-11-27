"""Simulated cases (FACTORY.md §4b): the simulated run's verdicts, recorded on the cases.

A repo with a `simulate` block in `.github/factory-testing.json` has a simulated environment whose
run plays every scenario in its pack after each staging deploy and posts a commit status
(`simulate.status_context`) whose `target_url` is the Actions run in `simulate.run_repo`. The
run's `report.json` (in the artifact `simulate.report_artifact`, default `sim-scenarios-report`)
names each scenario's result and the system test cases it `covers`.

`record` reads that result for one integration-branch commit and, for each epic at
`factory:in-staging` whose integration merge the commit carries:

* labels each covered case `factory:test-passed` (closing it) or `factory:test-failed`, with a
  comment naming the run and, for a failure, the failing steps as the runner wrote them;
* leaves a case alone whose fix is in flight (`factory:test-failed` with a `Blocked by` issue
  that is neither on staging nor closed): the next run after the fix lands records it;
* posts one summary on the epic: simulated passed and failed, manual still open, and any other
  failing scenario as a regression.

It opens no fix and starts no role: a person turns a failure into a fix with `Test Failed`
(or `Test Failed, expedite`). A run is recorded once per epic: the summary carries
`<!-- sim-run: <run id> -->`, and a run whose marker is already on the epic is skipped.

Two callers: a `status` event for the status context, and the reconcile sweep, which reads the
integration branch's head, so a missed or unsubscribed event costs one sweep interval.
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from collections.abc import Callable
from typing import Any

from .github_app import RepoPort, parse_json_or_empty
from .router import AGENT_MARK, RepoConfig, TEST_FAILED, TEST_PASSED, MANUAL_TEST, TEST_SKIPPED

log = logging.getLogger("factory-orchestrator.sim-results")

IN_STAGING = "factory:in-staging"
DEFAULT_ARTIFACT = "sim-scenarios-report"
FINAL = ("success", "failure", "error")
RUN_MARK = "<!-- sim-run: {run} -->"
CASE_MARK = "<!-- sim-run: {run} {sha} -->"
_RUN_URL = re.compile(r"/actions/runs/(\d+)")
_COVERS = re.compile(r"^([\w.-]+/[\w.-]+)#(\d+) (ST-\d+)$")
_CASE_TITLE = re.compile(r"^test\((\d+)\):\s*(ST-\d+)\b\s*(.*)$")
_EPIC_EXCLUDED = re.compile(r"^(task|test|bug)\(\d+\)")
_FIX = re.compile(r"(?:^|\n)\s*blocked by\s*#(\d+)", re.IGNORECASE)


def _names(labels: Any) -> list[str]:
    return [(x if isinstance(x, str) else x.get("name", "")) for x in labels or []]


def config(port: RepoPort) -> RepoConfig:
    return RepoConfig(
        testing=parse_json_or_empty(port.get_file(".github/factory-testing.json")),
        branches=parse_json_or_empty(port.get_file(".github/factory-branches.json")),
        profile=parse_json_or_empty(port.get_file(".factory/profile.json")),
    )


def latest_status(statuses: list[dict[str, Any]], context: str) -> dict[str, Any] | None:
    """The newest status for `context` (GitHub lists newest first)."""
    return next((s for s in statuses if s.get("context") == context), None)


def run_id_of(status: dict[str, Any]) -> int | None:
    m = _RUN_URL.search(status.get("target_url") or "")
    return int(m.group(1)) if m else None


def read_report(blob: bytes) -> dict[str, Any] | None:
    """`report.json` out of the artifact's zip, or None when it has none."""
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = next((n for n in z.namelist() if n.rsplit("/", 1)[-1] == "report.json"), None)
            if name is None:
                return None
            data = json.loads(z.read(name))
    except (zipfile.BadZipFile, ValueError, KeyError):
        return None
    return data if isinstance(data, dict) else None


def staging_epics(port: RepoPort) -> list[dict[str, Any]]:
    return [i for i in port.list_issues(labels=IN_STAGING)
            if not _EPIC_EXCLUDED.match(i.get("title") or "") and not i.get("pull_request")]


def carries(port: RepoPort, epic: int, sha: str, staging: str) -> bool:
    """True when `sha` carries the epic's integration merge. An epic with no merged
    `factory/epic-<n>` branch (no epic branches) is on staging by its label alone."""
    pr = port.merged_pr(f"factory/epic-{epic}", staging)
    merge = (pr or {}).get("merge_commit_sha")
    if not merge:
        return True
    return merge == sha or port.contains_commit(sha, merge)


def _already(port: RepoPort, epic: int, run: int) -> bool:
    mark = RUN_MARK.format(run=run)
    return any(mark in (c.get("body") or "") for c in port.list_comments(epic))


def _cases(port: RepoPort, epic: int) -> dict[str, dict[str, Any]]:
    """The epic's test cases by `ST-<n>`, open or closed."""
    out: dict[str, dict[str, Any]] = {}
    for i in port.list_issues(state="all"):
        m = _CASE_TITLE.match(i.get("title") or "")
        if m and int(m.group(1)) == epic:
            out[m.group(2)] = i
    return out


def _covers_epic(row: dict[str, Any], repo: str, epic: int) -> bool:
    for c in row.get("covers") or []:
        m = _COVERS.match(str(c))
        if m and m.group(1) == repo and int(m.group(2)) == epic:
            return True
    return False


def _in_flight(port: RepoPort, case: dict[str, Any]) -> bool:
    """True while an issue the case is `Blocked by` has not reached staging. A blocker on staging
    (`factory:in-staging`) or closed has landed, and the run is the case's to record: the case's
    `Blocked by` line is often the task it depends on, which is on staging before the first run,
    and holding it until that task closes at promotion would hold it past G3. A blocker that
    cannot be read counts as in flight."""
    for m in _FIX.finditer(case.get("body") or ""):
        try:
            blocker = port.get_issue(int(m.group(1)))
        except Exception:  # noqa: BLE001 - unreadable: hold, the next sweep looks again
            log.warning("Could not read #%s, which case #%s is blocked by", m.group(1), case.get("number"))
            return True
        if blocker is None:
            return True
        if blocker.get("state") != "closed" and IN_STAGING not in _names(blocker.get("labels")):
            return True
    return False


def _failure_text(row: dict[str, Any]) -> str:
    lines = [f"- {f}" for f in row.get("failures") or []] or [f"- the scenario ended `{row.get('result')}`"]
    return "\n".join(lines)


def record(port: RepoPort, *, sha: str | None = None, context: str | None = None,
           port_for: Callable[[str, str], RepoPort] | None = None) -> int:
    """Record the simulated run's verdicts for the integration branch's head (or `sha`).
    `context`, from a status event, skips every status but the simulated run's.
    Returns how many epics got a summary. Never raises for a missing or unfinished result."""
    cfg = config(port)
    sim = cfg.simulate
    staging = cfg.staging_branch
    if sim is None or staging is None:
        return 0
    if context is not None and context != sim["status_context"]:
        return 0
    epics = staging_epics(port)
    if not epics:
        return 0
    sha = sha or port.branch_sha(staging)
    if not sha:
        return 0
    status = latest_status(port.commit_statuses(sha), sim["status_context"])
    if status is None or status.get("state") not in FINAL:
        return 0
    run = run_id_of(status)
    if run is None:
        log.warning("%s on %s names no Actions run (%s) - nothing to read", sim["status_context"],
                    sha[:12], status.get("target_url"))
        return 0
    todo = [e for e in epics if not _already(port, e["number"], run)
            and carries(port, e["number"], sha, staging)]
    if not todo:
        return 0
    run_repo = sim.get("run_repo") or f"{port.owner}/{port.repo}"
    owner, name = run_repo.split("/", 1)
    reader = port if run_repo == f"{port.owner}/{port.repo}" else (port_for(owner, name) if port_for else None)
    if reader is None:
        log.warning("Cannot read %s's runs from %s/%s - no cross-repo access", run_repo, port.owner, port.repo)
        return 0
    blob = reader.run_artifact(run, sim.get("report_artifact") or DEFAULT_ARTIFACT)
    report = read_report(blob) if blob else None
    if report is None:
        # Not uploaded yet, expired, or unreadable: the next sweep tries again.
        log.warning("No report for run %s yet (%s) - will retry", run, run_repo)
        return 0
    run_url = status.get("target_url") or ""
    done = 0
    for epic in todo:
        _record_epic(port, epic, report, run, run_url, sha)
        done += 1
    return done


def _record_epic(port: RepoPort, epic: dict[str, Any], report: dict[str, Any], run: int,
                 run_url: str, sha: str) -> None:
    n = epic["number"]
    here = f"{port.owner}/{port.repo}"
    cases = _cases(port, n)
    rows = [r for r in report.get("scenarios") or [] if isinstance(r, dict)]
    mine: dict[str, dict[str, Any]] = {}
    for row in rows:
        for c in row.get("covers") or []:
            m = _COVERS.match(str(c))
            if m and m.group(1) == here and int(m.group(2)) == n:
                # Two scenarios covering one case: a failure in either is the case's.
                if mine.get(m.group(3), {}).get("result", "pass") == "pass":
                    mine[m.group(3)] = row
    passed, failed, held = [], [], []
    for case_id, row in sorted(mine.items(), key=lambda kv: int(kv[0][3:])):
        case = cases.get(case_id)
        if case is None:
            continue
        labels = _names(case.get("labels"))
        if TEST_FAILED in labels and _in_flight(port, case):
            held.append(case_id)  # its fix is in flight: the run after it lands records it
            continue
        ok = row.get("result") == "pass"
        (passed if ok else failed).append((case_id, case, row))
        mark = CASE_MARK.format(run=run, sha=sha)
        if ok:
            for lab in (MANUAL_TEST, TEST_FAILED):
                if lab in labels:
                    port.remove_label(case["number"], lab)
            if TEST_PASSED not in labels:
                port.add_labels(case["number"], [TEST_PASSED])
            port.create_comment(case["number"], "\n".join([
                f"**{case_id} passed in the simulated environment** — run [{run}]({run_url}) "
                f"on `{sha[:12]}`. Closing it.", "", mark, AGENT_MARK]))
            if case.get("state") != "closed":
                try:
                    port.update_issue_state(case["number"], "closed")  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001 - an open passed case is not a failed record
                    log.warning("Could not close case #%s", case["number"])
        else:
            for lab in (MANUAL_TEST, TEST_PASSED, TEST_SKIPPED):
                if lab in labels:
                    port.remove_label(case["number"], lab)
            if TEST_FAILED not in labels:
                port.add_labels(case["number"], [TEST_FAILED])
            if case.get("state") == "closed":
                try:
                    port.update_issue_state(case["number"], "open")  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    log.warning("Could not reopen case #%s", case["number"])
            port.create_comment(case["number"], "\n".join([
                f"**{case_id} failed in the simulated environment** — run [{run}]({run_url}) "
                f"on `{sha[:12]}`.", "", _failure_text(row), "",
                "**You need to:** decide at the production approval (G3). To have it fixed, comment "
                "`Test Failed` here, or `Test Failed, expedite` (an expedite approver) for a fix "
                "that builds itself. Nothing was filed yet.", "", mark, AGENT_MARK]))
    regressions = [r for r in rows if r.get("result") != "pass" and not _covers_epic(r, here, n)]
    manual_open = sorted(
        (cid for cid, c in cases.items()
         if cid not in mine and c.get("state") != "closed"
         and TEST_PASSED not in _names(c.get("labels")) and TEST_SKIPPED not in _names(c.get("labels"))),
        key=lambda cid: int(cid[3:]))
    port.create_comment(n, _summary(n, passed, failed, held, manual_open, regressions, run, run_url, sha))
    log.info("Recorded simulated run %s on epic #%s: %d passed, %d failed, %d held, %d regressions",
             run, n, len(passed), len(failed), len(held), len(regressions))


def _summary(epic: int, passed, failed, held, manual_open, regressions, run, run_url, sha) -> str:
    total = len(passed) + len(failed)
    head = (f"**Simulated tests: {len(passed)} of {total} passed**" if total else
            "**Simulated tests: none of this epic's cases ran in this run**")
    lines = [head + f" — run [{run}]({run_url}) on `{sha[:12]}`."]
    if failed:
        lines.append("**You need to:** look at the failed cases before the production approval (G3). "
                     "Each one says what failed; comment `Test Failed` on it to have it fixed.")
    else:
        lines.append("**You need to:** nothing for the simulated cases"
                     + (f"; {len(manual_open)} manual case(s) still need a tester." if manual_open else "."))
    for case_id, case, row in failed:
        first = (row.get("failures") or [f"ended {row.get('result')}"])[0]
        lines.append(f"- {case_id} failed: {first}")
    if held:
        lines.append(f"- Waiting on their fix, not recorded: {', '.join(held)}.")
    if manual_open:
        lines.append(f"- Manual, still open: {', '.join(manual_open)}.")
    if regressions:
        lines.append("- Also failing in this run (not this epic's cases): "
                     + ", ".join(f"`{r.get('name')}`" for r in regressions) + ".")
    lines += ["", RUN_MARK.format(run=run), AGENT_MARK]
    return "\n".join(lines)
