"""Run the shared conformance fixtures against the Python router.

The same JSON files drive scripts/test-router.js against the workflow's
inline JS router — this harness interpreting them identically is what makes
the fixtures the single source of routing truth (engine-contract spec).

Fixtures carrying a `config.orchestrator` key pin the *Actions engine's*
claim behaviour (stand-down) and are skipped here: the claim protocol is
engine-specific by design, and the Python half lives in test_claim.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest

from factory_orchestrator.router import RepoConfig, Router, release_chain

from .fake_repo import FakeRepo

CONF = Path(__file__).resolve().parents[1] / "conformance"
FIXTURES = sorted((CONF / "fixtures").glob("*.json"))
SCHEMA = json.loads((CONF / "fixture.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def load(path: Path) -> dict:
    fx = json.loads(path.read_text())
    VALIDATOR.validate(fx)
    return fx


def build_world(fx: dict) -> tuple[FakeRepo, dict[int, dict]]:
    milestones = {m["number"]: {"number": m["number"], "title": m["title"],
                                "html_url": m.get("htmlUrl", "u")}
                  for m in fx.get("repo", {}).get("milestones", [])}

    def ms(n):
        if n is None:
            return None
        return milestones.setdefault(n, {"number": n, "title": f"ms{n}", "html_url": "u"})

    issues, comments = {}, {}
    for i in fx.get("repo", {}).get("issues", []):
        issues[i["number"]] = {
            "number": i["number"], "title": i["title"], "body": i.get("body", ""),
            "labels": [{"name": x} for x in i.get("labels", [])],
            "user": {"type": i.get("authorType", "User")},
            "state": i.get("state", "open"),
            "milestone": ms(i.get("milestone")),
            **({"pull_request": {}} if i.get("isPullRequest") else {}),
        }
        if i.get("comments"):
            comments[i["number"]] = [{"body": c["body"]} for c in i["comments"]]
    return FakeRepo(issues, comments), milestones


def build_event(fx: dict, world: FakeRepo, milestones: dict) -> tuple[str, dict]:
    ev = fx["event"]

    def ms(n):
        return milestones.setdefault(n, {"number": n, "title": f"ms{n}", "html_url": "u"})

    if ev["name"] == "issues":
        payload: dict = {"action": ev["action"], "issue": world.issues[ev["issue"]]}
        if "label" in ev:
            payload["label"] = {"name": ev["label"]}
        if "sender" in ev:
            payload["sender"] = {"login": ev["sender"],
                                 "type": ev.get("senderType", "User")}
        if "milestone" in ev:
            payload["milestone"] = ms(ev["milestone"])
        return "issues", payload
    if ev["name"] == "issue_comment":
        c = ev["comment"]
        return "issue_comment", {
            "action": ev["action"], "issue": world.issues[ev["issue"]],
            "comment": {"body": c["body"],
                        "user": {"login": c["login"], "type": c.get("authorType", "User")},
                        "author_association": c.get("authorAssociation", "NONE")}}
    if ev["name"] == "milestone":
        return "milestone", {"action": ev["action"], "milestone": ms(ev["milestone"])}
    if ev["name"] == "push":
        return "push", {"ref": ev["ref"], "repository": {"default_branch": ev["defaultBranch"]}}
    if ev["name"] == "workflow_dispatch":
        return "workflow_dispatch", {"inputs": {"role": ev["role"], "issue_number": ev["issue"]}}
    raise ValueError(ev["name"])


def assert_expect(fx_name: str, expect: dict, world: FakeRepo, result, baseline: dict,
                  chain: tuple[list[str], int] | None) -> None:
    if "role" in expect:
        assert result.role == expect["role"], f"{fx_name}: role {result.role!r} != {expect['role']!r}"
    if "issues" in expect:
        assert result.issues == expect["issues"], f"{fx_name}: issues {result.issues}"
    if "releaseIssue" in expect:
        assert str(result.release_issue or "") == expect["releaseIssue"], \
            f"{fx_name}: releaseIssue {result.release_issue!r}"
    for n_str, want in expect.get("labels", {}).items():
        n = int(n_str)
        labels = world.labels_of(n) if n in world.issues else []
        for l in want.get("has", []):
            assert l in labels, f"{fx_name}: #{n} missing {l} (has {labels})"
        for l in want.get("not", []):
            assert l not in labels, f"{fx_name}: #{n} unexpectedly has {l}"
    for n_str, want in expect.get("comments", {}).items():
        n = int(n_str)
        fresh = world.comments.get(n, [])[baseline.get(n, 0):]
        bodies = [c["body"] for c in fresh]
        if "count" in want:
            assert len(fresh) == want["count"], f"{fx_name}: #{n} comments {bodies}"
        if "countAtLeast" in want:
            assert len(fresh) >= want["countAtLeast"], f"{fx_name}: #{n} comments {bodies}"
        for s in want.get("contains", []):
            assert any(s in b for b in bodies), f"{fx_name}: #{n} no comment contains {s!r}: {bodies}"
        for s in want.get("notContains", []):
            assert not any(s in b for b in bodies), f"{fx_name}: #{n} comment contains {s!r}"
    if "createdCount" in expect:
        assert len(world.created) == expect["createdCount"], \
            f"{fx_name}: created {[i['title'] for i in world.created]}"
    for idx, want in enumerate(expect.get("createdIssues", [])):
        assert idx < len(world.created), f"{fx_name}: created[{idx}] missing"
        got = world.created[idx]
        if "titlePattern" in want:
            assert re.search(want["titlePattern"], got["title"]), f"{fx_name}: {got['title']!r}"
        for l in want.get("labels", []):
            assert any((x if isinstance(x, str) else x["name"]) == l for x in got["labels"]), \
                f"{fx_name}: created[{idx}] not labelled {l}"
        for s in want.get("bodyContains", []):
            assert s in (got.get("body") or ""), f"{fx_name}: created[{idx}] body lacks {s!r}"
    if "chainIssues" in expect:
        assert chain is not None and chain[0] == expect["chainIssues"], f"{fx_name}: chain {chain}"
    if "chainCount" in expect:
        assert chain is not None and str(chain[1]) == expect["chainCount"], f"{fx_name}: chain {chain}"


def run_pass(fx: dict, world: FakeRepo, milestones: dict, expect: dict, fx_name: str) -> None:
    baseline = {n: len(cs) for n, cs in world.comments.items()}
    cfg = RepoConfig(
        release=_cfg(fx, "release"),
        approvers=_cfg(fx, "approvers"),
        branches=_cfg(fx, "branches"),
    )
    event_name, payload = build_event(fx, world, milestones)
    result = Router(world, cfg).route(event_name, payload)
    chain = None
    if fx.get("chain") == "release":
        rel = str(result.release_issue or expect.get("releaseIssue") or fx["expect"].get("releaseIssue", ""))
        chain = release_chain(world, int(rel)) if rel else ([], 0)
    assert_expect(fx_name, expect, world, result, baseline, chain)


def _cfg(fx: dict, key: str) -> dict:
    v = fx.get("config", {}).get(key)
    # "invalid-json" = file exists but does not parse = treated as absent.
    return v if isinstance(v, dict) else {}


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_fixture(path: Path) -> None:
    fx = load(path)
    if "orchestrator" in fx.get("config", {}):
        pytest.skip("claim fixture: pins the Actions engine's stand-down; "
                    "the Python half is tested in test_claim.py")
    world, milestones = build_world(fx)
    run_pass(fx, world, milestones, fx["expect"], fx["name"])
    if fx.get("repeatEvent"):
        run_pass(fx, world, milestones, fx.get("expectSecond", {}), fx["name"] + " (2nd)")
