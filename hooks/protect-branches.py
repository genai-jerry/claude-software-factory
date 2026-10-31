#!/usr/bin/env python3
"""Factory guard: block agent writes to protected branches.

PreToolUse hook. GitHub branch protection is unavailable on the current plan,
so this is the enforcement point: agents deliver via PRs from factory/*
branches; only a human lands code on protected branches (gate G3).

Blocks:
- Bash `git push` where any refspec destination is a protected branch
  (handles `main`, `main:main`, `HEAD:main`, `refs/heads/main`, `+main`,
  `--delete main`), and bare `git push` while the current branch is protected.
- GitHub MCP tools that write with a `branch` parameter targeting a protected
  branch (push_files, create_or_update_file, delete_file, ...).
- PR merge / auto-merge tools (backup for the settings.json deny list).
- `gh pr merge` onto a protected branch, and `gh api` calls that merge or move
  one: Bash reaches GitHub without any MCP tool.

The integration branch is protected too when the orchestrator says so: with
FACTORY_STAGING_GUARD=closed, this run has no release-to-staging approval
(gate GS) behind it and may not write to FACTORY_INTEGRATION_BRANCH (default
`staging`). A branch that does not exist yet may still be created, which is
what the roles' `auto_create` step does. Unset (the Actions engine), the
integration branch stays agent-writable.

Exit 2 = block (stderr is shown to the agent).
"""
import json
import os
import re
import shlex
import subprocess
import sys

MAIN_BRANCHES = {"main", "master"}
PROTECTED = set(MAIN_BRANCHES)
_MERGE_API = re.compile(r"/pulls/\d+/merge\b|/merges\b")
_REF_API = re.compile(r"/git/(?:refs|updates)/?(?:heads/)?([^\s?]*)")
BLOCKED_TOOLS = {
    "mcp__github__merge_pull_request",
    "mcp__github__enable_pr_auto_merge",
}


def staging_guarded():
    """The integration branch, when this run may not write to it; else None."""
    if os.environ.get("FACTORY_STAGING_GUARD") != "closed":
        return None
    return os.environ.get("FACTORY_INTEGRATION_BRANCH") or "staging"


def deny(reason):
    print(
        f"FACTORY GUARD: {reason} Protected branches ({', '.join(sorted(PROTECTED))}) "
        "only change after a person approves it: release to staging (GS) for the "
        "integration branch, production release (G3) for the default branch. "
        "Push to a factory/<issue>-<slug> branch and open a PR instead, or stop "
        "and say that the approval is missing.",
        file=sys.stderr,
    )
    sys.exit(2)


def remote_has(branch):
    """True unless GitHub says the branch is missing: an error must not unlock it."""
    try:
        out = subprocess.run(
            ["git", "ls-remote", "--exit-code", "--heads", "origin", branch],
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return True
    return out.returncode != 2


def blocked_dest(branch):
    """Is a push to this branch refused? Creating a missing integration branch is not."""
    if branch in MAIN_BRANCHES:
        return True
    return branch == staging_guarded() and remote_has(branch)


def pr_base(args):
    """The base branch of the PR a `gh pr merge` names; None if it cannot be read."""
    positional = [a for a in args if not a.startswith("-")]
    repo = None
    for flag in ("-R", "--repo"):
        if flag in args and args.index(flag) + 1 < len(args):
            repo = args[args.index(flag) + 1]
            positional = [a for a in positional if a != repo]
    cmd = ["gh", "pr", "view", *positional[:1], "--json", "baseRefName", "-q", ".baseRefName"]
    if repo:
        cmd += ["--repo", repo]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def check_gh(seg):
    if seg[1:3] == ["pr", "merge"]:
        base = pr_base(seg[3:])
        if base is None:
            deny("Could not read the base branch of the PR this `gh pr merge` names.")
        if base in PROTECTED:
            deny(f"`gh pr merge` targets protected branch '{base}'.")
    elif seg[1:2] == ["api"]:
        text = " ".join(seg[2:])
        if _MERGE_API.search(text):
            deny("`gh api` merge calls are not allowed; use `gh pr merge`.")
        m = _REF_API.search(text)
        if m and m.group(1).strip("/") in PROTECTED:
            deny(f"`gh api` targets protected branch '{m.group(1)}'.")


def dest_of(refspec):
    ref = refspec.lstrip("+")
    ref = ref.split(":", 1)[1] if ":" in ref else ref
    if ref.startswith("refs/heads/"):
        ref = ref[len("refs/heads/"):]
    return ref


def current_branch():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def check_bash(command):
    try:
        tokens = shlex.split(command)
    except ValueError:
        if "push" in command and "git" in command:
            deny("Could not safely parse a git push command.")
        return
    # split compound commands on shell operators
    segments, cur = [], []
    for t in tokens:
        if t in {"&&", "||", ";", "|", "&"}:
            segments.append(cur)
            cur = []
        else:
            cur.append(t)
    segments.append(cur)

    for seg in segments:
        if seg and seg[0].rsplit("/", 1)[-1] == "gh":
            check_gh(seg)
            continue
        if not seg or "git" not in seg[0].rsplit("/", 1)[-1]:
            continue
        if "push" not in seg:
            continue
        args = seg[seg.index("push") + 1:]
        positional = [a for a in args if not a.startswith("-")]
        # positional = [remote, refspec, refspec, ...]
        refspecs = positional[1:]
        if refspecs:
            for r in refspecs:
                if blocked_dest(dest_of(r)):
                    deny(f"git push targets protected branch '{dest_of(r)}'.")
        else:
            # bare `git push` (or remote only): destination = current branch
            if blocked_dest(current_branch()):
                deny("bare `git push` while checked out on a protected branch.")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    guarded = staging_guarded()
    if guarded:
        PROTECTED.add(guarded)

    if tool in BLOCKED_TOOLS:
        deny(f"tool '{tool}' is reserved for humans.")

    if tool == "Bash":
        check_bash(tool_input.get("command", ""))
    elif tool.startswith("mcp__github__"):
        branch = tool_input.get("branch") or tool_input.get("base") or ""
        if branch in PROTECTED and tool != "mcp__github__create_pull_request":
            deny(f"tool '{tool}' writes to protected branch '{branch}'.")

    sys.exit(0)


if __name__ == "__main__":
    main()
