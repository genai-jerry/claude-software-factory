#!/usr/bin/env python3
"""Factory guard: block agent pushes to protected branches (main/master).

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

Exit 2 = block (stderr is shown to the agent).
"""
import json
import shlex
import subprocess
import sys

PROTECTED = {"main", "master"}
BLOCKED_TOOLS = {
    "mcp__github__merge_pull_request",
    "mcp__github__enable_pr_auto_merge",
}


def deny(reason):
    print(
        f"FACTORY GUARD: {reason} Protected branches ({', '.join(sorted(PROTECTED))}) "
        "only change via pull requests merged by a human (gate G3). "
        "Push to a factory/<issue>-<slug> branch and open a PR instead.",
        file=sys.stderr,
    )
    sys.exit(2)


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
                if dest_of(r) in PROTECTED:
                    deny(f"git push targets protected branch '{dest_of(r)}'.")
        else:
            # bare `git push` (or remote only): destination = current branch
            if current_branch() in PROTECTED:
                deny("bare `git push` while checked out on a protected branch.")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

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
