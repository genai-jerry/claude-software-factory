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
import re
from pathlib import Path

from .router import BUG_KIND, EXPEDITE, IN_PROGRESS, RELEASE_KIND

log = logging.getLogger("factory-orchestrator.next-step")

NEXT_MARK = "factory-next:"
AGENT_MARK = "<!-- factory-agent -->"

#: The list a blocking comment ends with (FACTORY.md §1a rule 13). The notice
#: repeats it, so the questions are the last thing on the thread.
QUESTIONS_HEAD_RE = re.compile(r"^\s*\**questions? for you:?\**\s*(.*)$", re.IGNORECASE)
_ITEM_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.*\S)\s*$")
MAX_QUESTIONS = 8


def visible_part(body: str | None) -> str:
    """A comment without its fold, its markers and its code: what a person reads."""
    text = body or ""
    text = re.sub(r"<details>[\s\S]*?</details>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"<!--[\s\S]*?-->", " ", text)
    return text


def extract_questions(body: str | None, limit: int = MAX_QUESTIONS) -> list[str]:
    """The questions a blocking comment asks: its `Questions for you:` list,
    or — for a comment written before that rule — its lines that end in a
    question mark. Empty when it asks nothing a list can carry."""
    lines = visible_part(body).splitlines()
    for i, line in enumerate(lines):
        m = QUESTIONS_HEAD_RE.match(line)
        if not m:
            continue
        out: list[str] = []
        first = m.group(1).strip().strip("*").strip()
        if first:
            out.append(re.sub(r"^(?:\d+[.)]|[-*])\s+", "", first))
        for rest in lines[i + 1:]:
            item = _ITEM_RE.match(rest)
            if item:
                out.append(item.group(1).strip())
            elif rest.strip() == "":
                if out:
                    break
            else:
                break
        if out:
            return out[:limit]
    out = []
    for line in lines:
        s = re.sub(r"^\s*(?:\d+[.)]|[-*])\s+", "", line).strip().strip("*").strip()
        if s.endswith("?") and 8 <= len(s) <= 300 and s not in out:
            out.append(s)
    return out[:limit]


def newest_agent_question_body(comments: list[dict]) -> str:
    """The newest agent comment that is a role's own word — not a hand-off
    notice, not a run-started line — which is where the questions are."""
    for c in reversed(comments):
        body = c.get("body") or ""
        if AGENT_MARK not in body or NEXT_MARK in body:
            continue
        if visible_part(body).strip().startswith("▶"):
            continue
        return body
    return ""


def questions_block(questions: list[str] | None) -> str:
    if not questions:
        return ""
    return "**Questions for you:**\n" + "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1)) + "\n\n"
TABLE_PATH = Path("handbook") / "next-step.json"
#: Kind markers sit alongside the state label and are never the state itself.
NOT_A_STATE = {IN_PROGRESS, EXPEDITE, RELEASE_KIND, BUG_KIND}
GATE_OF_STATE = {
    "factory:release-ready": "release_scope",
    "factory:spec-ready": "spec",
    "factory:design-ready": "design",
    "factory:ready": "implementation",
    "factory:epic-ready": "staging",
    "factory:in-staging": "release",
    "factory:manual-test": "testers",
    "factory:bug-retest": "testers",
}
#: A gate whose own key is absent or empty borrows another's list. GS is the
#: only one: an estate that has not adopted `staging` keeps releasing to
#: staging under whoever already owns the production go (FACTORY.md §2b).
GATE_FALLBACK = {"staging": "release", "testers": "implementation"}


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
           approvers: list[str], expedited: bool = False, tested: bool = False,
           questions: list[str] | None = None) -> str:
    entry = table["states"].get(state) if state else None
    if entry is None:
        entry = table["none"]
    # An expedited state says the opposite of its normal wording: the factory
    # advances it, so the reader is owed "nothing to do" rather than a control
    # to press. Only the states expedite actually advances carry a variant.
    if expedited and isinstance(entry.get("expedited"), dict):
        entry = entry["expedited"]
    # Where the repo runs system tests (FACTORY.md §4b) two states have a
    # different story: an epic's build is not over when its tasks are, and a
    # landed task is waiting on cases as well as siblings. Only those two
    # carry a variant, and a repo without the policy never sees one.
    elif tested and isinstance(entry.get("tested"), dict):
        entry = entry["tested"]
    who_list = ", ".join("@" + u for u in approvers) if approvers else \
        "any owner, member or collaborator"

    def fill(text: str) -> str:
        return text.replace("{issue}", str(issue)).replace("{approvers}", who_list)

    where = f"now at `{state}`" if state else "carrying no `factory:*` state"
    return (
        f"**{role.capitalize()}** finished — #{issue} is {where}.\n\n"
        f"**Next: {fill(entry['who'])}.** {fill(entry['how'])}\n\n"
        f"{questions_block(questions)}"
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
