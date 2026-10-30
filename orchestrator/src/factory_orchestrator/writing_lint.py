"""Score a run's comments against FACTORY.md §1a (Writing for people).

Report-only: the scores go on the run's ledger row and in the log, and nothing
is ever changed or blocked over style. The checker is the factory repo's
`scripts/comment-lint.js`, so both engines score with the same code; this module
only finds the comments a run posted and hands them over.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .router import AGENT_MARK

log = logging.getLogger("factory-orchestrator.writing")

LINT_SCRIPT = Path("scripts") / "comment-lint.js"


def score_new_comments(port, issue: int, before_count: int,
                       factory_path: Path | None) -> dict[str, Any] | None:
    """Lint the agent comments added to `issue` since `before_count`; None if unscored."""
    if factory_path is None or not (factory_path / LINT_SCRIPT).is_file():
        return None
    node = shutil.which("node")
    if node is None:
        return None
    try:
        new = [c for c in port.list_comments(issue)[before_count:]
               if AGENT_MARK in (c.get("body") or "")]
    except Exception:  # noqa: BLE001 - scoring must never fail a run
        log.warning("could not read comments to score on #%s", issue, exc_info=True)
        return None
    if not new:
        return None
    try:
        proc = subprocess.run(
            [node, str(factory_path / LINT_SCRIPT), "--json"],
            input=json.dumps([{"body": c.get("body", "")} for c in new]),
            capture_output=True, text=True, timeout=20, check=True)
        report = json.loads(proc.stdout)
    except (subprocess.SubprocessError, OSError, ValueError):
        log.warning("comment lint failed on #%s", issue, exc_info=True)
        return None
    results = report.get("results", [])
    return {
        "summary": report.get("summary", {}),
        "comments": [{"kind": r.get("kind"), "words": r.get("words"),
                      "problems": r.get("problems", [])} for r in results],
    }
