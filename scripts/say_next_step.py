#!/usr/bin/env python3
"""Post "what happens next" on the issue a factory role just finished with.

Every run has to leave the issue saying what is expected of the next actor.
Before this, a role that finished cleanly said nothing at all: the label moved
and the thread went quiet, and whoever was watching had to know the state
machine by heart to work out whether it was their turn. States with no trigger
of their own (`factory:in-review`, `factory:in-test`, `factory:ready-to-ship`)
were the worst of it — the pipeline was waiting for a human to start the next
role, and nothing on the issue said so.

The wording lives in handbook/next-step.json, which the orchestrator engine
renders too (factory_orchestrator.next_step) — one table, both engines.

Runs after the no-op guard on purpose: this comment must never be the
"visible trace" that lets a role which did nothing pass as a role that worked.

Environment: GH_TOKEN, GITHUB_REPOSITORY (owner/name), ISSUE, ROLE.
Never fails the run — a missing notice is a smaller problem than a red job.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

AGENT_MARK = "<!-- factory-agent -->"
NEXT_MARK = "factory-next:"
IN_PROGRESS = "factory:in-progress"
EXPEDITE = "factory:expedite"
# Kind markers, not states: they sit alongside the state label (FACTORY.md §3).
NOT_A_STATE = {IN_PROGRESS, EXPEDITE, "factory:release", "factory:bug"}
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


def gh(*args: str) -> str:
    out = subprocess.run(["gh", *args], capture_output=True, text=True,
                         timeout=60, check=False)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"gh {' '.join(args)} failed")
    return out.stdout


def state_of(labels: list[str]) -> str | None:
    """The one `factory:*` state on the issue, markers and kinds excluded."""
    states = [x for x in labels if x.startswith("factory:") and x not in NOT_A_STATE]
    # Drift can leave more than one; the last applied is what the router uses.
    return states[-1] if states else None


def approver_list(gate: str, path: str = ".github/factory-approvers.json") -> list[str]:
    try:
        config = json.loads(pathlib.Path(path).read_text())
    except Exception:  # noqa: BLE001 - absent or unparseable means "no list"
        return []
    for key in (gate, GATE_FALLBACK.get(gate)):
        if key is None:
            continue
        value = config.get(key)
        names = [x for x in value if isinstance(x, str)] if isinstance(value, list) else []
        if names:
            return names
    return []


def render_who_how(table: dict, state: str | None, issue: int,
                   approvers: list[str], expedited: bool = False,
                   tested: bool = False) -> tuple[str, str]:
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
    who = ", ".join("@" + u for u in approvers) if approvers else \
        "any owner, member or collaborator"

    def fill(text: str) -> str:
        return text.replace("{issue}", str(issue)).replace("{approvers}", who)

    return fill(entry["who"]), fill(entry["how"])


def expedited_for(repo: str, data: dict) -> bool:
    """True when this issue advances itself (FACTORY.md §4a).

    The marker lives on the epic and is never copied onto tasks, so a task
    has to look its epic up: `task(<n>)` gives the number, a qualified
    `Part of owner/repo#n` marker gives the repo when the epic is elsewhere.
    Best-effort like everything else here — an unreadable epic just means the
    un-expedited wording, which is the safe way to be wrong.
    """
    labels = [l["name"] for l in data.get("labels", [])]
    if EXPEDITE in labels:
        return True
    m = re.match(r"^task\((\d+)\)", data.get("title") or "")
    if not m:
        return False
    epic, where = m.group(1), repo
    qualified = re.search(r"(?:^|\n)\s*part of\s*:?\s*([\w.-]+/[\w.-]+)#\d+",
                          data.get("body") or "", re.IGNORECASE)
    if qualified:
        where = qualified.group(1)
    try:
        parent = json.loads(gh("api", f"repos/{where}/issues/{epic}"))
    except Exception:  # noqa: BLE001 - no cross-repo access, or a stale number
        return False
    return EXPEDITE in [l["name"] for l in parent.get("labels", [])]


def system_tests_on(path: str = ".github/factory-testing.json") -> bool:
    """The repo's system-test policy (FACTORY.md §4b). Absent or unparseable
    is off, which is what every repo that has not adopted them wants."""
    try:
        return json.loads(pathlib.Path(path).read_text()).get("system_tests") is True
    except Exception:  # noqa: BLE001 - an unreadable policy is not an enabled one
        return False


# The list a blocking comment ends with (FACTORY.md §1a rule 13). The notice
# repeats it, so the questions are the last thing on the thread. Byte-for-byte
# the orchestrator's (factory_orchestrator.next_step), which the tests check.
QUESTIONS_HEAD_RE = re.compile(r"^\s*\**questions? for you:?\**\s*(.*)$", re.IGNORECASE)
_ITEM_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.*\S)\s*$")
MAX_QUESTIONS = 8


def visible_part(body: str | None) -> str:
    text = body or ""
    text = re.sub(r"<details>[\s\S]*?</details>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"<!--[\s\S]*?-->", " ", text)
    return text


def extract_questions(body: str | None, limit: int = MAX_QUESTIONS) -> list[str]:
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


def render(table: dict, role: str, issue: int, state: str | None,
           approvers: list[str], expedited: bool = False, tested: bool = False,
           questions: list[str] | None = None) -> str:
    who, how = render_who_how(table, state, issue, approvers, expedited, tested)
    where = f"now at `{state}`" if state else "carrying no `factory:*` state"
    return (
        f"**{role.capitalize()}** finished — #{issue} is {where}.\n\n"
        f"**Next: {who}.** {how}\n\n"
        f"{questions_block(questions)}"
        f"<!-- {NEXT_MARK}{state or 'none'} -->\n"
        f"{AGENT_MARK}"
    )


def already_said(comments: list[dict], state: str | None) -> bool:
    """True when the newest hand-off notice on the thread is this same one.

    Not "has this state ever been announced": a task bounced back from review
    re-enters `factory:ready` and has to be announced again. Another state's
    notice in between is what makes it new.
    """
    for c in reversed(comments):
        body = c.get("body") or ""
        if NEXT_MARK in body:
            return f"<!-- {NEXT_MARK}{state or 'none'} -->" in body
    return False


def main() -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    issue = int(os.environ["ISSUE"])
    role = os.environ.get("ROLE") or "factory"
    table_path = pathlib.Path(__file__).resolve().parent.parent / "handbook" / "next-step.json"
    table = json.loads(table_path.read_text())

    data = json.loads(gh("api", f"repos/{repo}/issues/{issue}"))
    labels = [l["name"] for l in data.get("labels", [])]
    state = state_of(labels)
    comments = json.loads(gh("api", "--paginate", f"repos/{repo}/issues/{issue}/comments"))
    if already_said(comments, state):
        print(f"#{issue} already carries the hand-off notice for {state} - not repeating it.")
        return 0

    gate = GATE_OF_STATE.get(state or "")
    questions = extract_questions(newest_agent_question_body(comments)) \
        if state == "factory:blocked" else []
    body = render(table, role, issue, state, approver_list(gate) if gate else [],
                  expedited_for(repo, data), system_tests_on(), questions)
    gh("api", f"repos/{repo}/issues/{issue}/comments", "-f", f"body={body}")
    print(f"Said what happens next on #{issue} ({state or 'no state'}).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 - never fail a good run over a notice
        print(f"::warning::Could not post the hand-off notice: {e}")
        sys.exit(0)
