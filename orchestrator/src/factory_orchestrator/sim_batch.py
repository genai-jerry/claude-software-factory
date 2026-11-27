"""Simulated runs for a batch of releases (FACTORY.md §4b, Simulated cases).

Every staging deploy of a repo with a `simulate` block starts a simulated run. When several
epics' releases wait for the same staging, one run after the last of them tests all of them:

* While more releases wait their turn on staging, a release run gets `FACTORY_SIM_LATER=1`.
  The Release Manager then ends each integration merge commit's message with the line
  `Sim-scenarios: later` (commands/release.md, step 7), and the simulated environment only
  queues that deploy: the commit's status says it waits for the next run.
* When a release run ends with no other release waiting, and the integration branch's head
  says `Sim-scenarios: later`, nothing else would start a run: the factory starts one by hand
  (`workflow_dispatch` on `simulate.workflow`, default `sim-scenarios.yml`, in
  `simulate.run_repo`) with `after=<owner>/<repo>@<head>`. That run waits for the head's deploy
  to reach the simulated stack, takes every queued commit and reports on all of them.

If the run cannot be started (the App lacks Actions: write on the run repo, say), the epic is
told how to start it by hand. Nothing is lost either way: the commits stay queued, and the
next deploy that is not held back runs them too.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from .github_app import RepoPort

log = logging.getLogger("factory-orchestrator.sim-batch")

LATER_LINE = "Sim-scenarios: later"
DEFAULT_WORKFLOW = "sim-scenarios.yml"
_LATER = re.compile(r"^Sim-scenarios:[ \t]*later[ \t]*$", re.IGNORECASE | re.MULTILINE)


def says_later(message: str | None) -> bool:
    """The commit message holds the line that queues its deploy without a run."""
    return bool(message and _LATER.search(message))


def later_env(simulate: dict[str, Any] | None, waiting: int) -> dict[str, str]:
    """The release run's environment: hold the simulated run back while others wait."""
    return {"FACTORY_SIM_LATER": "1"} if simulate and waiting > 0 else {}


class BatchRunError(RuntimeError):
    """The batch's run could not be started for `head`."""

    def __init__(self, head: str, error: Exception):
        super().__init__(str(error))
        self.head = head
        self.error = error


def start_batch_run(port: RepoPort, simulate: dict[str, Any] | None, staging: str | None,
                    port_for: Callable[[str, str], RepoPort] | None,
                    started: set[str]) -> str | None:
    """Start the one simulated run a held-back batch is waiting for. Returns the head it covers.

    Only when the integration branch's head was merged with `Sim-scenarios: later`: any other
    head's deploy started (or will start) its own run. `started` keeps the heads already
    started for (or failed to start for), so a head gets one try however many release runs end
    on it. Raises BatchRunError when the run could not be started.
    """
    if not simulate or not staging:
        return None
    head = port.branch_sha(staging)
    if not head or head in started:
        return None
    if not says_later(port.commit_message(head)):
        return None
    here = f"{port.owner}/{port.repo}"
    run_repo = simulate.get("run_repo") or here
    workflow = simulate.get("workflow") or DEFAULT_WORKFLOW
    started.add(head)
    try:
        owner, name = run_repo.split("/", 1)
        runner = port if run_repo == here else (port_for(owner, name) if port_for else None)
        if runner is None:
            raise RuntimeError(f"no access to {run_repo}")
        runner.dispatch_workflow(workflow, ref=runner.default_branch(), inputs={"after": f"{here}@{head}"})
    except Exception as e:  # noqa: BLE001 - said on the epic by the caller
        raise BatchRunError(head, e) from e
    log.info("Started %s in %s for %s@%s, the last of a held-back batch", workflow, run_repo, here, head[:12])
    return head


def how_to_start(port: RepoPort, simulate: dict[str, Any], head: str, error: Exception) -> str:
    """The comment for an epic when the batch's run could not be started."""
    here = f"{port.owner}/{port.repo}"
    run_repo = simulate.get("run_repo") or here
    workflow = simulate.get("workflow") or DEFAULT_WORKFLOW
    return (f"The simulated tests for this release were held back until the last release in the "
            f"batch, and the factory could not start that run ({error}).\n\n"
            f"Start it by hand: in {run_repo}, Actions > {workflow} > Run workflow, with "
            f"`after` set to `{here}@{head}`. Until then the simulated cases wait.")
