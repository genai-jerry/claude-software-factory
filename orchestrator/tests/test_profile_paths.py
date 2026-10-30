"""The profile-relevant paths are one list in three places; keep them equal."""

import re
from pathlib import Path

import yaml

from factory_orchestrator.router import PROFILE_PATHS, push_touches_profile

ROOT = Path(__file__).resolve().parents[2]


def test_python_list_matches_the_actions_caller_stub():
    stub = yaml.safe_load((ROOT / "templates/workflows/factory-pipeline.yml").read_text())
    on = stub.get("on", stub.get(True))          # PyYAML reads a bare `on:` key as True
    assert tuple(on["push"]["paths"]) == PROFILE_PATHS


def test_python_list_matches_the_js_router():
    src = (ROOT / ".github/workflows/factory-pipeline.yml").read_text()
    block = re.search(r"const PROFILE_PATHS = \[(.*?)\];", src, re.S).group(1)
    assert tuple(re.findall(r"'([^']+)'", block)) == PROFILE_PATHS


def push(*files):
    return {"commits": [{"added": [], "modified": list(files), "removed": []}]}


def test_paths_match_like_the_actions_filter():
    assert push_touches_profile(push("package.json"))
    assert push_touches_profile(push("apps/web/package.json"))
    assert push_touches_profile(push("requirements-dev.txt"))
    assert push_touches_profile(push("docker-compose.prod.yml"))
    assert push_touches_profile(push(".github/workflows/ci/deploy.yml"))
    assert not push_touches_profile(push("src/app.ts", "docs/package.json.md"))
    assert not push_touches_profile(push(".factory/profile.json"))
    assert not push_touches_profile(push("sub/Makefile.inc"))


def test_no_file_lists_counts_as_relevant():
    assert push_touches_profile({})
    assert push_touches_profile({"commits": []})
