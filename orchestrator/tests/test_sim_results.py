"""Simulated cases (FACTORY.md §4b): recording a simulated run's verdicts on an epic's cases."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from factory_orchestrator import sim_results

from .fake_repo import FakeRepo

REPO = "o/r"
SHA = "a" * 40
RUN = 4401
URL = f"https://github.com/o/infra/actions/runs/{RUN}"
TESTING = {"system_tests": True, "run_on": "staging",
           "simulate": {"pack": "beacon/sim/scenarios", "status_context": "beacon/sim-scenarios",
                        "run_repo": "o/infra"}}


def _zip(report: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("report.json", json.dumps(report))
        z.writestr("report.md", "# report")
    return buf.getvalue()


def _row(name: str, result: str, *cases: str, failures: list[str] | None = None) -> dict:
    return {"name": name, "result": result, "failures": failures or [],
            "covers": [f"{REPO}#9 {c}" for c in cases]}


class SimRepo(FakeRepo):
    """FakeRepo with files, commit statuses, merged PRs, ancestry and run artifacts."""

    def __init__(self, *a, files=None, statuses_by_sha=None, artifacts=None, merged=None,
                 ancestors=None, **kw):
        super().__init__(*a, **kw)
        self.files = files or {}
        self.statuses_by_sha = statuses_by_sha or {}
        self.artifacts = artifacts or {}
        self.merged = merged or {}
        self.ancestors = ancestors or set()

    def get_file(self, path, ref=None):
        return self.files.get(path)

    def commit_statuses(self, sha):
        return list(self.statuses_by_sha.get(sha, []))

    def contains_commit(self, sha, ancestor):
        return (sha, ancestor) in self.ancestors

    def merged_pr(self, head, base):
        return self.merged.get((head, base))

    def run_artifact(self, run_id, name):
        return self.artifacts.get((run_id, name))


def _world(report: dict | None, *, state="failure", cases=None, epic_labels=("factory:in-staging",),
           merged_sha=None, carried=True, comments=None):
    issues = {9: {"number": 9, "title": "Calling rules", "labels": [{"name": x} for x in epic_labels],
                  "state": "open", "body": ""}}
    for n, (title, labels, body, st) in (cases or {}).items():
        issues[n] = {"number": n, "title": title, "labels": [{"name": x} for x in labels],
                     "body": body, "state": st}
    repo = SimRepo(issues=issues, comments=comments or {},
                   files={".github/factory-testing.json": json.dumps(TESTING),
                          ".github/factory-branches.json": json.dumps({"staging": "staging", "epics": True})},
                   statuses_by_sha={SHA: [{"context": "ci", "state": "success"},
                                          {"context": "beacon/sim-scenarios", "state": state, "target_url": URL}]},
                   merged={("factory/epic-9", "staging"): {"merge_commit_sha": merged_sha}} if merged_sha else {},
                   ancestors={(SHA, merged_sha)} if (merged_sha and carried) else set())
    repo.branch_shas["staging"] = SHA
    infra = SimRepo(owner="o", repo="infra",
                    artifacts={(RUN, "sim-scenarios-report"): _zip(report)} if report is not None else {})
    return repo, infra


def _cases():
    return {30: ("test(9): ST-21 New lead tried on days 1, 2, 9 and 10", ["factory:manual-test"], "", "open"),
            31: ("test(9): ST-25 Cap at 4 gives Lost", ["factory:manual-test"], "", "open"),
            32: ("test(9): ST-1 Answered call shows Connected", ["factory:manual-test"],
                 "**Execution:** manual — real audio on a real phone", "open")}


def _record(repo, infra, **kw):
    return sim_results.record(repo, port_for=lambda o, r: infra if r == "infra" else repo, **kw)


def _labels(repo, n):
    return set(repo.labels_of(n))


def test_a_pass_and_a_fail_are_recorded_on_their_cases_and_summarised_on_the_epic():
    report = {"scenarios": [_row("667-st-21", "pass", "ST-21"),
                            _row("667-st-25", "fail", "ST-25", failures=["step 7 (expect): expected exactly 4 calls, found 5"])]}
    repo, infra = _world(report, cases=_cases())
    assert _record(repo, infra) == 1
    assert _labels(repo, 30) == {"factory:test-passed"} and repo.issues[30]["state"] == "closed"
    assert _labels(repo, 31) == {"factory:test-failed"} and repo.issues[31]["state"] == "open"
    assert "factory:manual-test" in _labels(repo, 32)  # a manual case is left alone
    failed = repo.comments[31][-1]["body"]
    assert "ST-25 failed in the simulated environment" in failed
    assert "step 7 (expect): expected exactly 4 calls, found 5" in failed
    assert "`Test Failed, expedite`" in failed and "Nothing was filed yet" in failed
    summary = repo.comments[9][-1]["body"]
    assert "Simulated tests: 1 of 2 passed" in summary and "ST-25 failed" in summary
    assert "Manual, still open: ST-1" in summary
    assert f"<!-- sim-run: {RUN} -->" in summary
    assert not repo.created  # no fix is filed


def test_a_run_is_recorded_once():
    report = {"scenarios": [_row("667-st-21", "pass", "ST-21")]}
    repo, infra = _world(report, cases=_cases())
    assert _record(repo, infra) == 1
    before = {n: len(c) for n, c in repo.comments.items()}
    assert _record(repo, infra) == 0
    assert {n: len(c) for n, c in repo.comments.items()} == before


def test_an_unfinished_run_and_a_missing_report_record_nothing():
    repo, infra = _world({"scenarios": []}, state="pending", cases=_cases())
    assert _record(repo, infra) == 0
    repo, infra = _world(None, cases=_cases())  # not uploaded yet: the next sweep tries again
    assert _record(repo, infra) == 0 and not repo.comments.get(9)


def test_a_commit_without_the_epics_integration_merge_records_nothing():
    report = {"scenarios": [_row("667-st-21", "pass", "ST-21")]}
    repo, infra = _world(report, cases=_cases(), merged_sha="b" * 40, carried=False)
    assert _record(repo, infra) == 0
    repo, infra = _world(report, cases=_cases(), merged_sha="b" * 40, carried=True)
    assert _record(repo, infra) == 1


def test_an_epic_not_on_staging_and_a_repo_without_the_block_record_nothing():
    report = {"scenarios": [_row("667-st-21", "pass", "ST-21")]}
    repo, infra = _world(report, cases=_cases(), epic_labels=("factory:epic-ready",))
    assert _record(repo, infra) == 0
    repo, infra = _world(report, cases=_cases())
    repo.files[".github/factory-testing.json"] = json.dumps({"system_tests": True})
    assert _record(repo, infra) == 0


def test_a_case_whose_fix_is_in_flight_is_left_for_the_run_after_the_fix():
    cases = _cases()
    cases[31] = (cases[31][0], ["factory:test-failed"], "Blocked by #77", "open")
    report = {"scenarios": [_row("667-st-25", "pass", "ST-25")]}
    repo, infra = _world(report, cases=cases)
    _record(repo, infra)
    assert _labels(repo, 31) == {"factory:test-failed"} and not repo.comments.get(31)
    assert "Waiting on their fix, not recorded: ST-25" in repo.comments[9][-1]["body"]


def test_a_case_blocked_by_an_issue_already_on_staging_is_recorded():
    """1042 ST-5 passed but stayed held: its `Blocked by` was the task it depends on, on staging."""
    cases = _cases()
    cases[31] = (cases[31][0], ["factory:test-failed"], "Blocked by #77", "open")
    report = {"scenarios": [_row("667-st-25", "pass", "ST-25")]}
    repo, infra = _world(report, cases=cases)
    repo.issues[77] = {"number": 77, "title": "task(9): the fix", "body": "", "state": "open",
                       "labels": [{"name": "factory:in-staging"}]}
    _record(repo, infra)
    assert _labels(repo, 31) == {"factory:test-passed"} and repo.issues[31]["state"] == "closed"
    assert "Waiting on their fix" not in repo.comments[9][-1]["body"]


def test_a_case_blocked_by_a_closed_issue_is_recorded_and_an_open_one_holds_it():
    for state, labels, held in (("closed", [], False), ("open", [{"name": "factory:in-progress"}], True)):
        cases = _cases()
        cases[31] = (cases[31][0], ["factory:test-failed"], "Blocked by #77", "open")
        repo, infra = _world({"scenarios": [_row("667-st-25", "fail", "ST-25")]}, cases=cases)
        repo.issues[77] = {"number": 77, "title": "fix", "body": "", "state": state, "labels": labels}
        _record(repo, infra)
        assert bool(repo.comments.get(31)) is not held, state


def test_a_newer_run_records_a_case_again_either_way():
    cases = _cases()
    cases[31] = (cases[31][0], ["factory:test-failed"], "", "open")  # failed by an earlier run, no fix
    cases[30] = (cases[30][0], ["factory:test-passed"], "", "closed")
    report = {"scenarios": [_row("667-st-25", "pass", "ST-25"), _row("667-st-21", "fail", "ST-21")]}
    repo, infra = _world(report, cases=cases)
    _record(repo, infra)
    assert _labels(repo, 31) == {"factory:test-passed"} and repo.issues[31]["state"] == "closed"
    assert _labels(repo, 30) == {"factory:test-failed"} and repo.issues[30]["state"] == "open"


def test_another_scenario_failing_is_named_as_a_regression():
    report = {"scenarios": [_row("667-st-21", "pass", "ST-21"), _row("retry-gaps", "fail"),
                            {"name": "old-epic-st-2", "result": "error", "failures": ["x"],
                             "covers": ["o/r#553 ST-2"]}]}
    repo, infra = _world(report, cases=_cases())
    _record(repo, infra)
    summary = repo.comments[9][-1]["body"]
    assert "Also failing in this run (not this epic's cases): `retry-gaps`, `old-epic-st-2`" in summary


def test_a_status_event_for_another_context_reads_nothing():
    repo, infra = _world({"scenarios": [_row("667-st-21", "pass", "ST-21")]}, cases=_cases())
    assert _record(repo, infra, sha=SHA, context="ci") == 0
    assert _record(repo, infra, sha=SHA, context="beacon/sim-scenarios") == 1


@pytest.mark.parametrize("blob", [b"not a zip", _zip([1, 2])])
def test_an_unreadable_report_records_nothing(blob):
    repo, infra = _world(None, cases=_cases())
    infra.artifacts[(RUN, "sim-scenarios-report")] = blob
    assert _record(repo, infra) == 0
