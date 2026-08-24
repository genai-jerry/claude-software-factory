"""The Python half of the exactly-one-engine guarantee.

The standdown-*/orchestrator-config-* fixtures pin the Actions engine's
side (stand down when an external engine is named). These tests pin this
engine's side against the same configurations, asserting complementarity:
for every declared engine value, exactly one of the two engines acts.
"""

import json
from pathlib import Path

import pytest

from factory_orchestrator.claim import claim_check, declared_engine, orchestrator_settings

from .fake_repo import FakeRepo

FIXDIR = Path(__file__).resolve().parents[1] / "conformance" / "fixtures"


class ConfigRepo(FakeRepo):
    def __init__(self, content: str | None):
        super().__init__()
        self._content = content

    def get_file(self, path, ref=None):
        if path == ".github/factory-orchestrator.json":
            return self._content
        return None


@pytest.mark.parametrize("content,engine", [
    (json.dumps({"engine": "langgraph"}), "langgraph"),
    (json.dumps({"engine": "github-actions"}), "github-actions"),
    (json.dumps({"engine": ""}), "github-actions"),
    (json.dumps({"other": 1}), "github-actions"),
    ("{not json", "github-actions"),
    (None, "github-actions"),
])
def test_declared_engine(content, engine):
    assert declared_engine(ConfigRepo(content)) == engine


def test_claim_check_only_for_named_engine():
    assert claim_check(ConfigRepo(json.dumps({"engine": "langgraph"})), "langgraph")
    assert not claim_check(ConfigRepo(json.dumps({"engine": "github-actions"})), "langgraph")
    assert not claim_check(ConfigRepo(None), "langgraph")
    assert not claim_check(ConfigRepo("{not json"), "langgraph")


def test_settings_passthrough():
    repo = ConfigRepo(json.dumps({"engine": "langgraph", "runners": {"max_parallel": 2}}))
    assert orchestrator_settings(repo)["runners"]["max_parallel"] == 2


def test_complementarity_with_actions_fixtures():
    """For every claim fixture, exactly one engine acts."""
    claim_fixtures = [json.loads(p.read_text()) for p in sorted(FIXDIR.glob("*.json"))
                      if "orchestrator" in json.loads(p.read_text()).get("config", {})]
    assert claim_fixtures, "claim fixtures missing"
    for fx in claim_fixtures:
        orch = fx["config"]["orchestrator"]
        content = json.dumps(orch) if isinstance(orch, dict) else "{not json"
        langgraph_acts = claim_check(ConfigRepo(content), "langgraph")
        # The fixture's expect encodes the Actions side: role "none" for every
        # event means Actions stood down.
        actions_acts = fx["expect"].get("role") != "none"
        assert langgraph_acts != actions_acts, (
            f"{fx['name']}: both engines "
            f"{'acted' if langgraph_acts else 'stood down'} for {orch!r}")
