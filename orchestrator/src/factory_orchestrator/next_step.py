"""What is expected of the next actor, said on the issue after every run.

The wording is not here: it is `handbook/next-step.json` in the factory repo,
which the Actions engine renders too (scripts/say_next_step.py). This module
is the orchestrator's half — find the table in the factory checkout the role
runner already makes, fill it in, and decide whether it still needs saying.

Before this, a role that finished cleanly left the issue silent. The states
with no trigger of their own — `factory:in-review`, `factory:in-test`,
`factory:ready-to-ship` — were the pipeline waiting on a human to start the
next role, with nothing on the issue that said so.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .router import EXPEDITE, IN_PROGRESS, RELEASE_KIND

log = logging.getLogger("factory-orchestrator.next-step")

NEXT_MARK = "factory-next:"
TABLE_PATH = Path("handbook") / "next-step.json"
#: Kind markers sit alongside the state label and are never the state itself.
NOT_A_STATE = {IN_PROGRESS, EXPEDITE, RELEASE_KIND}
GATE_OF_STATE = {
    "factory:release-ready": "release_scope",
    "factory:spec-ready": "spec",
    "factory:design-ready": "design",
    "factory:ready": "implementation",
    "factory:epic-ready": "staging",
    "factory:in-staging": "release",
}
#: A gate whose own key is absent or empty borrows another's list. GS is the
#: only one: an estate that has not adopted `staging` keeps releasing to
#: staging under whoever already owns the production go (FACTORY.md §2b).
GATE_FALLBACK = {"staging": "release"}


def load_table(factory_checkout: Path | None) -> dict | None:
    """The shared table, or None when it cannot be read (an older factory ref)."""
    if factory_checkout is None:
        return None
    path = Path(factory_checkout) / TABLE_PATH
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001 - an old factory ref simply has no table
        log.warning("no hand-off table at %s - skipping the notice", path)
        return None


def state_of(labels: list[str]) -> str | None:
    states = [x for x in labels if x.startswith("factory:") and x not in NOT_A_STATE]
    return states[-1] if states else None


def approvers_for(state: str | None, config: dict) -> list[str]:
    """The gate list a state's notice names, honouring the GS fallback."""
    gate = GATE_OF_STATE.get(state or "")
    if not gate:
        return []
    for key in (gate, GATE_FALLBACK.get(gate)):
        if key is None:
            continue
        value = config.get(key)
        names = [x for x in value if isinstance(x, str)] if isinstance(value, list) else []
        if names:
            return names
    return []


def render(table: dict, role: str, issue: int, state: str | None,
           approvers: list[str], expedited: bool = False) -> str:
    entry = table["states"].get(state) if state else None
    if entry is None:
        entry = table["none"]
    # An expedited state says the opposite of its normal wording: the factory
    # advances it, so the reader is owed "nothing to do" rather than a control
    # to press. Only the states expedite actually advances carry a variant.
    if expedited and isinstance(entry.get("expedited"), dict):
        entry = entry["expedited"]
    who_list = ", ".join("@" + u for u in approvers) if approvers else \
        "any owner, member or collaborator"

    def fill(text: str) -> str:
        return text.replace("{issue}", str(issue)).replace("{approvers}", who_list)

    where = f"now at `{state}`" if state else "carrying no `factory:*` state"
    return (
        f"**{role.capitalize()}** finished — #{issue} is {where}.\n\n"
        f"**Next: {fill(entry['who'])}.** {fill(entry['how'])}\n\n"
        f"<!-- {NEXT_MARK}{state or 'none'} -->"
    )


def already_said(comments: list[dict], state: str | None) -> bool:
    """True when the newest hand-off notice on the thread is this same one.

    Not "has this state ever been announced": a task the reviewer sends back
    re-enters `factory:ready` and has to be announced again. Another state's
    notice in between is what makes it new.
    """
    for c in reversed(comments):
        if NEXT_MARK in (c.get("body") or ""):
            return f"<!-- {NEXT_MARK}{state or 'none'} -->" in (c.get("body") or "")
    return False
