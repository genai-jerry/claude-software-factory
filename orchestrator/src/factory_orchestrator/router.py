"""The factory routing decision table, ported from the Actions engine.

This is a line-faithful port of the `route` and `release-chain` script
bodies in `.github/workflows/factory-pipeline.yml`. Parity is enforced by
the shared conformance fixtures (`orchestrator/conformance/fixtures/`),
which both implementations run in CI — when routing behaviour changes, the
fixtures and BOTH routers move in one PR. Reply texts are copied verbatim:
they are part of the visible trace contract.

The router mutates GitHub through a :class:`~.github_app.RepoPort` exactly
where the JS router calls the REST API, and returns the decision. It never
runs a role itself — the graph does that — and it contains no claim check:
whether this engine should be acting at all is decided by
:mod:`factory_orchestrator.claim` before routing.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .github_app import RepoPort

log = logging.getLogger("factory-orchestrator.router")

RELEASE_KIND = "factory:release"
FAST_TRACK = "factory:fast-track"
FAST_TRACK_DONE = "<!-- factory-fast-track-done -->"
PROFILE_KIND = "factory:profile"
PROFILE_TITLE = "Factory: repo profile"
IN_PROGRESS = "factory:in-progress"
ORTHOGONAL = [IN_PROGRESS, "factory:blocked"]
AGENT_MARK = "<!-- factory-agent -->"


@dataclass
class RouteResult:
    role: str = "none"
    issue: str = ""
    issues: list[str] = field(default_factory=list)
    release_issue: str = ""
    #: owner/name the role runs against, when that is not the event's own
    #: repo. A cross-repo epic (FACTORY.md §7) keeps its tasks in one repo and
    #: the epic in another, and the role that answers a task event then has to
    #: run over there. Empty means "the repo the event came from".
    repo: str = ""


@dataclass
class RepoConfig:
    """Parsed contents of the consuming repo's factory config files."""

    release: dict[str, Any] = field(default_factory=dict)
    approvers: dict[str, Any] = field(default_factory=dict)
    branches: dict[str, Any] = field(default_factory=dict)

    @property
    def gating(self) -> bool:
        return (self.release.get("gating") or "none") == "milestone"

    @property
    def epics(self) -> bool:
        """Epic-branch policy (FACTORY.md §6b): absent file or key is False."""
        return self.branches.get("epics") is True

    @property
    def exempt_labels(self) -> list[str]:
        v = self.release.get("exempt_labels")
        return v if isinstance(v, list) else ["factory:fast-track"]

    @property
    def auto_tracker(self) -> bool:
        return self.release.get("auto_create_release_issue") is not False

    def approver_list(self, gate: str) -> list[str]:
        v = self.approvers.get(gate)
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


#: "Part of owner/repo#250" — the qualified parent marker (FACTORY.md §7).
#: The unqualified forms mean the task's own repo.
_EPIC_REF_RE = re.compile(
    r"(?:^|\n)\s*(?:part of|parent|epic)\s*:?\s*"
    r"(?:https?://[^/\s]+/([\w.-]+)/([\w.-]+)/issues/(\d+)"
    r"|([\w.-]+)/([\w.-]+)#(\d+)"
    r"|#(\d+))",
    re.IGNORECASE,
)


def epic_ref_from_body(body: str | None) -> tuple[str | None, int | None]:
    """The epic an issue body points at, as (owner/repo or None, number)."""
    m = _EPIC_REF_RE.search(body or "")
    if not m:
        return None, None
    if m.group(3):
        return f"{m.group(1)}/{m.group(2)}", int(m.group(3))
    if m.group(6):
        return f"{m.group(4)}/{m.group(5)}", int(m.group(6))
    return None, int(m.group(7))


def _sender_is_app(payload: dict[str, Any]) -> bool:
    """True when the actor is a GitHub App rather than a person.

    `sender.type` is what GitHub sets; the `[bot]` login suffix is the
    fallback for payloads (and fixtures) that carry only a login.
    """
    sender = payload.get("sender") or {}
    login = sender.get("login") or ""
    return sender.get("type") == "Bot" or login.endswith("[bot]")


def _names(labels: list[Any] | None) -> list[str]:
    return [(l if isinstance(l, str) else l.get("name")) for l in (labels or [])]


def _is_task_title(title: str | None) -> bool:
    return bool(re.match(r"^task\(\d+\)", title or ""))


class Router:
    def __init__(self, port: RepoPort, config: RepoConfig,
                 port_for: Callable[[str, str], RepoPort] | None = None):
        self.port = port
        self.cfg = config
        #: How to reach a repo that is not this event's own. Without it a
        #: cross-repo lookup is skipped rather than guessed at.
        self.port_for = port_for

    # -- helpers mirroring the JS router ----------------------------------
    def say(self, n: int, body: str) -> None:
        self.port.create_comment(n, f"{body}\n\n{AGENT_MARK}")

    def drop_label(self, n: int, name: str) -> None:
        self.port.remove_label(n, name)

    def not_started(self, names: list[str]) -> bool:
        allowed = ["factory:backlog", "factory:intake", *ORTHOGONAL]
        return all(x in allowed for x in names if x.startswith("factory:"))

    def state_of(self, names: list[str]) -> str:
        states = [x for x in names
                  if x.startswith("factory:") and x not in ORTHOGONAL
                  and x not in (RELEASE_KIND, FAST_TRACK, PROFILE_KIND)]
        return ", ".join(states) or "no factory:* state label"

    def tracker_for(self, ms_number: int) -> dict[str, Any] | None:
        found = self.port.list_issues(labels=RELEASE_KIND, state="all")
        pat = re.compile(rf"^release\({ms_number}\):")
        for x in found:
            if x.get("pull_request") is None and pat.match(x.get("title") or ""):
                return x
        return None

    def ensure_tracker(self, milestone: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.tracker_for(milestone["number"])
        if existing:
            return existing
        if not self.cfg.auto_tracker:
            return None
        cc = ", ".join("@" + u for u in self.cfg.approver_list("release_scope"))
        body_lines = [
            f"Release tracker for milestone [{milestone['title']}]({milestone.get('html_url', '')}).",
            "",
            "**Nothing is running yet — this release is waiting on a human.**",
            "Requirement issues filed against this milestone wait in `factory:backlog`",
            "and no factory agent touches them until gate G0 is approved here.",
            "",
            "To start it:",
            "",
            "1. Comment `Plan release` here to run the **Scrum Master**: it reads every",
            "   issue in the milestone and posts a release plan — scope, sequencing,",
            "   risks and open questions — then moves this tracker to",
            "   `factory:release-ready`.",
            "2. When the plan looks right, an approver comments the single word",
            "   `Approved` here (gate G0). Every backlog issue in the milestone then",
            "   enters intake as one batch.",
            "",
            *( [f"cc {cc} — this release cannot start without one of you.", ""] if cc else [] ),
            "Managed by the Software Factory — see FACTORY.md §2d.",
            "",
            AGENT_MARK,
        ]
        data = self.port.create_issue(
            title=f"release({milestone['number']}): {milestone['title']}",
            milestone=milestone["number"],
            labels=[RELEASE_KIND, "factory:release-planning"],
            body="\n".join(body_lines))
        log.info("Created release tracker #%s for milestone %s", data["number"], milestone["number"])
        return data

    def profile_issue(self) -> dict[str, Any] | None:
        found = self.port.list_issues(labels=PROFILE_KIND, state="all")
        for x in found:
            if x.get("pull_request") is None:
                return x
        return None

    def ensure_profile_issue(self) -> dict[str, Any]:
        existing = self.profile_issue()
        if existing:
            if existing.get("state") == "closed":
                try:
                    self.port.update_issue_state(existing["number"], "open")  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001 - best-effort, like the JS .catch
                    pass
            return existing
        body_lines = [
            "Home of this repository's `.factory/profile.json` (FACTORY.md §2c) — the stack facts",
            "every factory role treats as authoritative for this repo.",
            "",
            "The **Profiler** posts here whenever it drafts or re-checks the profile, and opens a PR",
            "when something it verified disagrees with the file. Nothing is applied without that PR",
            "being merged by a human.",
            "",
            f"To re-run it: remove and re-apply the `{PROFILE_KIND}` label on this issue.",
            "",
            AGENT_MARK,
        ]
        data = self.port.create_issue(title=PROFILE_TITLE, labels=[PROFILE_KIND],
                                      body="\n".join(body_lines))
        log.info("Created the profile issue #%s", data["number"])
        return data

    def say_once(self, n: int, marker: str, body: str) -> bool:
        try:
            said = self.port.list_comments(n)
        except Exception:  # noqa: BLE001
            said = []
        if any(marker in (c.get("body") or "") for c in said):
            return False
        self.say(n, f"{body}\n\n{marker}")
        return True

    def fast_track_done(self, n: int) -> bool:
        try:
            said = self.port.list_comments(n)
        except Exception:  # noqa: BLE001
            said = []
        return any(FAST_TRACK_DONE in (c.get("body") or "") for c in said)

    def queued_notice(self, n: int, ms: dict[str, Any] | None,
                      tracker: dict[str, Any] | None) -> None:
        if not tracker or not ms:
            return
        if "factory:release-approved" in _names(tracker.get("labels")):
            return
        self.say_once(n, f"<!-- factory-queued:{tracker['number']} -->", "\n".join([
            f"Queued for release **{ms['title']}** — tracked in #{tracker['number']}.",
            "",
            "Nothing runs on this issue yet, and nothing will until that release is",
            "approved at **gate G0**. To move it along, on #" + str(tracker["number"]) + ":",
            "",
            "1. comment `Plan release` to get the release plan, then",
            "2. comment `Approved` to release every issue in the milestone into intake.",
        ]))

    # -- the decision table ------------------------------------------------
    def route(self, event_name: str, payload: dict[str, Any]) -> RouteResult:
        r = RouteResult()
        cfg = self.cfg

        if event_name == "workflow_dispatch":
            inputs = payload.get("inputs") or {}
            r.role = inputs.get("role") or "none"
            r.issue = str(inputs.get("issue_number") or "")
            if r.role == "scrum":
                r.release_issue = r.issue

        elif event_name == "milestone":
            ms = payload.get("milestone") or {}
            if not cfg.gating:
                log.info("Release gating is off (.github/factory-release.json) - ignoring milestone event")
            elif payload.get("action") in ("created", "opened"):
                tracker = self.ensure_tracker(ms)
                if tracker:
                    r.issue = str(tracker["number"])
            else:
                log.info("Milestone %s - nothing to route", payload.get("action"))

        elif event_name == "issue_comment":
            self._route_comment(payload, r)

        elif event_name == "issues":
            self._route_issues(payload, r)

        elif event_name == "push":
            ref = payload.get("ref") or ""
            default = (payload.get("repository") or {}).get("default_branch") or ""
            if not default or ref != f"refs/heads/{default}":
                log.info("Push to %s - profile drift is only checked on the default branch",
                         ref or "(unknown ref)")
            else:
                prof = self.ensure_profile_issue()
                r.issue = str(prof["number"])
                r.role = "profiler"
                log.info("Profile-relevant paths changed on %s - re-checking on #%s", ref, r.issue)

        if r.role != "none" and not r.issues and r.issue:
            r.issues = [r.issue]
        if r.role != "none" and not r.issues:
            log.info("Role %s has no issue to run against - dropping it", r.role)
            r.role = "none"
        log.info("route: role=%s issue=%s issues=%s release_issue=%s",
                 r.role, r.issue, r.issues, r.release_issue or "-")
        return r

    # -- issue_comment ------------------------------------------------------
    def _route_comment(self, payload: dict[str, Any], r: RouteResult) -> None:
        cfg = self.cfg
        i = payload["issue"]
        r.issue = str(i["number"])
        body = (payload.get("comment") or {}).get("body") or ""
        author = (payload.get("comment") or {}).get("user") or {}
        sender = author.get("login")
        labels = _names(i.get("labels"))
        is_approval = bool(re.match(r"^\s*approved\s*[.!]?\s*$", body, re.IGNORECASE))
        is_plan_release = bool(re.match(r"^\s*plan\s+release\s*[.!]?\s*$", body, re.IGNORECASE))
        is_review_done = bool(re.match(r"^\s*review\s+done\s*[.!]?\s*$", body, re.IGNORECASE))
        is_tracker = RELEASE_KIND in labels
        assoc_ok = (payload.get("comment") or {}).get("author_association") in (
            "OWNER", "MEMBER", "COLLABORATOR")

        def authorized(gate: str) -> bool:
            lst = cfg.approver_list(gate)
            return sender in lst if lst else assoc_ok

        def refuse(gate: str, what: str) -> None:
            lst = cfg.approver_list(gate)
            self.say(i["number"], f"@{sender} — {what} requires " + (
                f"approval from: {', '.join('@' + u for u in lst)} (see .github/factory-approvers.json)."
                if lst else "owner, member or collaborator access on this repository."))

        # `pull_request` may be an empty object — presence is what matters
        # (JS truthiness of {} vs Python's).
        if i.get("pull_request") is not None:
            log.info("PR comment - skipping")
        elif author.get("type") == "Bot":
            log.info("Bot comment - skipping")
        elif AGENT_MARK in body:
            log.info("Factory agent comment (marker present) - skipping")
        elif is_tracker and is_plan_release:
            if not authorized("release_scope"):
                refuse("release_scope", "planning a release")
            else:
                r.role = "scrum"
                r.release_issue = r.issue
                log.info("Release planning requested - starting the Scrum Master")
        elif is_tracker and is_approval:
            if "factory:release-ready" not in labels:
                self.say(i["number"],
                         f'"Approved" has no effect while this release is at **{self.state_of(labels)}**.\n\n'
                         "Comment `Plan release` first — the Scrum Master reads the milestone, posts the "
                         "release plan and moves this tracker to `factory:release-ready`, which is gate G0.")
            elif not authorized("release_scope"):
                refuse("release_scope", "gate G0 (release approval)")
            else:
                self.drop_label(i["number"], "factory:release-ready")
                self.port.add_labels(i["number"], ["factory:release-approved"])
                r.release_issue = r.issue
                log.info("Gate G0 approved via comment - releasing the milestone")
        elif is_review_done and "factory:in-review" in labels:
            # A human review substitutes for the Reviewer agent: the same
            # "clean" verdict shape (factory:in-review -> factory:in-test)
            # without running it. There is no "changes requested" equivalent
            # here — a human who found problems reviews the draft PR directly
            # on GitHub instead of commenting here.
            if not assoc_ok:
                self.say(i["number"],
                         f"@{sender} — marking a review done requires owner, member or collaborator access "
                         "on this repository.")
            elif IN_PROGRESS in labels:
                # Mirrors the factory:ready/Approved race guard: the Reviewer
                # may be mid-run producing this very verdict.
                self.say(i["number"],
                         "`Review Done` has no effect right now — a factory run is already live on this "
                         "issue (`factory:in-progress`).\n\n"
                         "The Reviewer may already be working out this verdict; marking it done now would "
                         "race its own result. Wait for the marker to clear, then comment again if the task "
                         "is still `factory:in-review`.")
                log.info("A run is already live on #%s - not skipping the Reviewer", i["number"])
            else:
                self.drop_label(i["number"], "factory:in-review")
                self.port.add_labels(i["number"], ["factory:in-test"])
                self.say(i["number"],
                         f"Marked reviewed by @{sender} — skipping the automated Reviewer, moving to "
                         "`factory:in-test`. This shortcut only relabels the task; if the draft PR is still "
                         "marked draft, mark it ready for review yourself.")
                log.info("Review marked done via comment - skipping the Reviewer")
        elif is_approval and "factory:ready" in labels:
            if not authorized("implementation"):
                refuse("implementation", "starting implementation")
            elif IN_PROGRESS in labels:
                # A second start is the one thing the state cannot refuse on its
                # own: the implementer only leaves factory:ready when it flips to
                # factory:in-review at the end, so the label still reads "ready"
                # for the whole run and a second Approved would route a second
                # implementer onto the same task and the same branch. The run
                # marker is the fact that answers it.
                self.say(i["number"],
                         "`Approved` has no effect right now — a factory run is already live on this "
                         "issue (`factory:in-progress`).\n\n"
                         "The implementer is still working; approving again would start a second one on "
                         "the same task and the same branch. The marker is removed when the run ends, "
                         "whatever the outcome — if this task is still `factory:ready` then, approve "
                         "again to restart it.")
                log.info("A run is already live on #%s - not starting a second implementer", i["number"])
            else:
                r.role = "implementer"
                log.info("Implementation approved via comment - starting implementer")
        elif is_approval and ("factory:spec-ready" in labels or "factory:design-ready" in labels):
            spec = "factory:spec-ready" in labels
            gate_key = "spec" if spec else "design"
            if not authorized(gate_key):
                refuse(gate_key, f"this gate ({'G1 spec' if spec else 'G2 design'} approval)")
                return
            head_branch = f"factory/{i['number']}-spec" if spec else f"factory/{i['number']}-design"
            prs = self.port.list_open_prs(head=f"{self.port.owner}:{head_branch}")
            # Epic-branch policy (FACTORY.md §6b): with epics:true a gate
            # document merges into the epic branch, not the default branch.
            # Both gates are adoption points for an in-flight epic, and the
            # branch is ensured whether or not there is a PR to retarget: the
            # gate is also reachable by a human merging the document PR
            # themselves (the factory offers that route in as many words), and
            # keying adoption on an open PR meant that route silently left the
            # epic on legacy routing for the rest of its life.
            #
            # Cutting the branch here loses nothing even when a document has
            # already merged to the default branch: it is cut FROM that branch,
            # so it carries the merged spec, and no task PR can have merged yet
            # — tasks are dispatched only after G2. The reverse retarget
            # handles a flip back to epics:false.
            epic_branch = f"factory/epic-{i['number']}"
            def_branch = self.port.default_branch()
            #
            # Best-effort: a repo that refuses the branch (permissions, a
            # protected-name rule) must still get its gate approved. Failing
            # here would lose the approval itself, which is worse than the
            # epic finishing on default-branch routing.
            epic_ready = self.cfg.epics
            if self.cfg.epics and not self.port.branch_exists(epic_branch):
                try:
                    self.port.create_branch(epic_branch, def_branch)
                    log.info("Created epic branch %s from %s", epic_branch, def_branch)
                except Exception as e:  # noqa: BLE001
                    epic_ready = False
                    log.warning("Could not create epic branch %s from %s (%s) - "
                                "this epic stays on default-branch routing",
                                epic_branch, def_branch, e)
            all_merged = True
            for pr in prs:
                try:
                    base = (pr.get("base") or {}).get("ref")
                    want = base
                    if epic_ready and base == def_branch:
                        want = epic_branch
                    elif not self.cfg.epics and base == epic_branch:
                        want = def_branch
                    if want != base:
                        self.port.update_pr_base(pr["number"], want)
                        log.info("Retargeted gate PR #%s: base %s -> %s (epic-branch policy §6b)",
                                 pr["number"], base, want)
                    self.port.merge_pr(pr["number"], "squash")
                    log.info("Merged gate PR #%s", pr["number"])
                except Exception as e:  # noqa: BLE001
                    all_merged = False
                    self.say(i["number"],
                             f"Approval noted, but PR #{pr['number']} could not be merged automatically ({e}). "
                             "Please merge it manually and apply the next label.")
            if not prs:
                log.info("No open gate PR on %s (already merged manually?) - proceeding", head_branch)
            if all_merged:
                self.drop_label(i["number"], "factory:spec-ready" if spec else "factory:design-ready")
                self.port.add_labels(i["number"],
                                     ["factory:spec-approved" if spec else "factory:design-approved"])
                r.role = "planner" if spec else "dispatch"
                log.info("Gate approved via comment - continuing with %s", r.role)
        elif "factory:blocked" not in labels:
            if is_approval:
                self.say(i["number"],
                         f'"Approved" has no effect while this is at **{self.state_of(labels)}** — nothing was started.\n\n'
                         "It advances the pipeline from:\n"
                         "- `factory:release-ready` (a release tracker) — approves gate G0 and releases the whole milestone\n"
                         "- `factory:spec-ready` — approves gate G1 and starts the planner\n"
                         "- `factory:design-ready` — approves gate G2 and starts the dispatcher\n"
                         "- `factory:ready` (a task sub-issue) — starts its implementer\n\n"
                         + ("This issue is in the backlog: add it to a release milestone, then approve that "
                            "release's tracker issue.\n\n" if "factory:backlog" in labels else "")
                         + ("This is merged onto its epic branch and green there (FACTORY.md §6b). The "
                            "Release Manager carries the completed epic to the integration branch with the "
                            "integration PR — nothing here needs a comment approval.\n\n"
                            if "factory:on-epic" in labels else "")
                         + ("This is at gate G3: it is already on the integration branch and green there, and "
                            "ships when a human merges the promotion PR(s) the Release Manager listed. That "
                            "merge click is the gate — there is nothing here for a comment to approve.\n\n"
                            if "factory:in-staging" in labels else "")
                         + 'From any other state, use Actions → "Factory pipeline" → Run workflow with the role you want. '
                           "Gate G3 (production) is deliberately not comment-approvable.")
            elif is_plan_release:
                pms = i.get("milestone")
                t = self.tracker_for(pms["number"]) if pms else None
                self.say(i["number"],
                         "`Plan release` only works on a **release tracker** — the issue labelled "
                         "`factory:release` that the factory opens for a milestone. This is a requirement "
                         "issue, so nothing was started.\n\n"
                         + (f"Its release is tracked in #{t['number']} — comment `Plan release` there."
                            if t else
                            (f"**{pms['title']}** has no release tracker yet; one is opened when the milestone "
                             "is created or first used." if pms else
                             "This issue is not in a milestone, so there is no release to plan.")))
            elif is_review_done:
                self.say(i["number"],
                         f'"Review Done" has no effect while this is at **{self.state_of(labels)}** — nothing '
                         "changed.\n\n"
                         "It only applies to `factory:in-review`: marking a human review complete so the task "
                         "moves to `factory:in-test` without waiting on the Reviewer agent.")
            log.info("Issue not factory:blocked - comments only resume blocked stages or approve gates")
        else:
            resume = {
                "factory:release-planning": "scrum",
                "factory:intake": "intake",
                "factory:spec-approved": "planner",
                "factory:planned": "architect",
                "factory:design-approved": "dispatch",
            }
            for lbl, role in resume.items():
                if lbl in labels:
                    r.role = role
                    break
            if r.role == "none" and all(
                    x == "factory:blocked" for x in labels
                    if x.startswith("factory:") and x != IN_PROGRESS):
                r.role = "scrum" if is_tracker else "intake"
            if r.role != "none":
                log.info("Human reply on blocked issue - resuming %s", r.role)
                if r.role == "scrum":
                    r.release_issue = r.issue
                self.drop_label(i["number"], "factory:blocked")
            else:
                self.say(i["number"],
                         f"This issue is `factory:blocked` at **{self.state_of(labels)}**, which has no automatic resume "
                         "step — your reply did not restart anything. Use Actions → \"Factory pipeline\" → Run workflow "
                         "with the role you want and this issue number.")
                log.info("Blocked at a stage without an automatic resume mapping - use Run workflow")

    # -- issues -------------------------------------------------------------
    def _route_issues(self, payload: dict[str, Any], r: RouteResult) -> None:
        cfg = self.cfg
        i = payload["issue"]
        r.issue = str(i["number"])
        labels = _names(i.get("labels"))
        states = [x for x in labels if x.startswith("factory:") and x != IN_PROGRESS]
        action = payload.get("action")

        if action == "opened":
            if (i.get("user") or {}).get("type") == "Bot":
                log.info("Bot-authored issue - skipping")
            elif RELEASE_KIND in labels:
                log.info("Release tracker issue - skipping")
            elif _is_task_title(i.get("title")):
                log.info("Factory task sub-issue - skipping")
            elif FAST_TRACK in labels:
                r.role = "fasttrack"
                log.info("Filed as factory:fast-track - running the fast lane")
            elif PROFILE_KIND in labels:
                r.role = "profiler"
                log.info("Filed as factory:profile - drafting the repo profile")
            elif any(x != "factory:intake" for x in states):
                log.info("Issue already carries a factory state - skipping")
            else:
                parked = False
                if cfg.gating and not any(x in cfg.exempt_labels for x in labels):
                    ms = i.get("milestone")
                    tracker = self.ensure_tracker(ms) if ms else None
                    approved = tracker and "factory:release-approved" in _names(tracker.get("labels"))
                    if not approved:
                        parked = True
                        self.drop_label(i["number"], "factory:intake")
                        self.port.add_labels(i["number"], ["factory:backlog"])
                        if tracker:
                            self.queued_notice(i["number"], ms, tracker)
                        else:
                            self.say(i["number"],
                                     (f"Queued for release **{ms['title']}** — that milestone has no release tracker "
                                      "(`auto_create_release_issue` is off), so nothing can approve it yet.\n\n"
                                      "Open a `release(<milestone>)` tracker issue for it, or approve gate G0 by hand.")
                                     if ms else
                                     ("Parked in `factory:backlog` — this repo runs **release-gated intake**.\n\n"
                                      "Add this issue to a milestone (the milestone *is* the release). The factory "
                                      "opens a release tracker for it; comment `Plan release` there to get a release "
                                      "plan, and approve it to start every issue in the release at once.\n\n"
                                      f"A small change does not need a release slot: `{FAST_TRACK}` skips this "
                                      "queue and hands it to the fast lane, which implements it and opens a PR for review."))
                        log.info("Release gating on - parked in factory:backlog")
                    else:
                        log.info("Milestone %s is already released - entering intake now", ms["number"])
                if not parked:
                    if "factory:intake" not in labels:
                        self.port.add_labels(i["number"], ["factory:intake"])
                        log.info("Applied factory:intake")
                    r.role = "intake"

        elif action in ("milestoned", "demilestoned"):
            ms = payload.get("milestone")
            if not cfg.gating:
                log.info("Release gating is off - milestone changes are informational only")
            elif ((i.get("user") or {}).get("type") == "Bot" or RELEASE_KIND in labels
                  or _is_task_title(i.get("title"))):
                log.info("Release tracker or factory sub-issue - skipping")
            elif any(x in cfg.exempt_labels for x in labels):
                log.info("Issue is exempt from release gating - skipping")
            elif not self.not_started(labels):
                log.info("Issue is already in flight (%s) - milestone change does not move it",
                         ", ".join(states))
            elif action == "milestoned":
                tracker = self.ensure_tracker(ms) if ms else None
                approved = tracker and "factory:release-approved" in _names(tracker.get("labels"))
                if approved:
                    self.drop_label(i["number"], "factory:backlog")
                    if "factory:intake" not in labels:
                        self.port.add_labels(i["number"], ["factory:intake"])
                    r.role = "intake"
                    self.say(i["number"],
                             f"Added to **{ms['title']}**, which is already approved "
                             f"({'#' + str(tracker['number']) if tracker else ''}) — entering intake now.")
                elif "factory:backlog" not in labels:
                    self.drop_label(i["number"], "factory:intake")
                    self.port.add_labels(i["number"], ["factory:backlog"])
                    self.queued_notice(i["number"], ms, tracker)
                    log.info("Queued in milestone %s - waiting for gate G0", ms["number"])
                else:
                    self.queued_notice(i["number"], ms, tracker)
                    log.info("Queued in milestone %s - already in factory:backlog", ms["number"])
            elif "factory:backlog" not in labels:
                self.drop_label(i["number"], "factory:intake")
                self.port.add_labels(i["number"], ["factory:backlog"])
                self.say(i["number"],
                         f"Removed from **{ms['title'] if ms else 'its milestone'}** — parked in "
                         "`factory:backlog` until it is part of an approved release.")

        elif action == "closed":
            m = re.match(r"^task\((\d+)\)", i.get("title") or "")
            if not m:
                log.info("Not a factory task sub-issue - nothing to re-dispatch")
            else:
                # The epic is not necessarily in this repo. A cross-repo epic
                # (FACTORY.md §7) keeps its tasks in the repos that implement
                # them and the epic where it was filed; the task body carries
                # the qualified "Part of owner/repo#N" marker for exactly
                # this. Looking #N up here instead found nothing — or, worse,
                # a completely unrelated issue that happens to have that
                # number — so the dependents of every closed task in a
                # cross-repo epic were silently never released.
                epic = m.group(1)
                epic_repo, body_number = epic_ref_from_body(i.get("body"))
                if body_number is not None and str(body_number) != epic:
                    # The title's task(N) is authoritative for the number.
                    log.info("Task #%s body points at #%s but its title says task(%s) - "
                             "trusting the title", i["number"], body_number, epic)
                    epic_repo = None
                port = self.port
                if epic_repo and epic_repo != f"{self.port.owner}/{self.port.repo}":
                    if self.port_for is None:
                        log.warning("Task #%s belongs to epic %s#%s in another repo and this "
                                    "engine has no cross-repo access - not re-dispatching",
                                    i["number"], epic_repo, epic)
                        return
                    owner, name = epic_repo.split("/", 1)
                    port = self.port_for(owner, name)
                parent = port.get_issue(int(epic))
                parent_labels = _names(parent.get("labels")) if parent else []
                where = epic_repo or f"{self.port.owner}/{self.port.repo}"
                if "factory:design-approved" not in parent_labels:
                    log.info("Epic %s#%s is not factory:design-approved - not re-dispatching",
                             where, epic)
                else:
                    r.role = "dispatch"
                    r.issue = epic
                    if port is not self.port:
                        r.repo = epic_repo
                    log.info("Task #%s closed - re-dispatching epic %s#%s to release dependents",
                             i["number"], where, epic)

        elif action == "labeled":
            name = (payload.get("label") or {}).get("name")
            sender = (payload.get("sender") or {}).get("login")
            if name == IN_PROGRESS:
                log.info("%s is a run marker applied by this pipeline - nothing to route", IN_PROGRESS)
                return
            gate_of = {
                "factory:release-approved": "release_scope",
                "factory:spec-approved": "spec",
                "factory:design-approved": "design",
            }
            role_map = {"factory:spec-approved": "planner", "factory:design-approved": "dispatch"}
            if name in gate_of:
                lst = cfg.approver_list(gate_of[name])
                # The revert exists to stop a person hand-applying an approved
                # label to walk past a gate. It must not fire on the factory's
                # own writes: this engine acts as a GitHub App, whose label
                # changes DO emit events (the Actions engine's workflow token
                # does not, which is why only this side ever saw it). Without
                # the exemption the router reverted the very label it had just
                # applied after a gate approval, and the epic ended up
                # carrying no state at all — not design-approved, not
                # design-ready, nothing, with the whole chain silently
                # stranded behind it. Same reasoning as the comment router
                # skipping Bot authors: an App's write is the factory's, and
                # the factory only applies these after it has authorised them.
                if lst and sender not in lst and not _sender_is_app(payload):
                    self.drop_label(i["number"], name)
                    self.say(i["number"],
                             f"`{name}` was applied by @{sender}, but this gate requires "
                             f"{', '.join('@' + u for u in lst)} (see .github/factory-approvers.json). Reverted.")
                elif name == "factory:release-approved":
                    self.drop_label(i["number"], "factory:release-ready")
                    r.release_issue = r.issue
                else:
                    r.role = role_map[name]
            notify_of = {
                "factory:release-ready": ("release_scope", "Gate G0 (release approval)"),
                "factory:spec-ready": ("spec", "Gate G1 (spec approval)"),
                "factory:design-ready": ("design", "Gate G2 (design approval)"),
                "factory:in-staging": ("release", "Gate G3 (promotion to the default branch)"),
                "factory:ready": ("implementation", "Implementation start"),
            }
            if name in notify_of:
                gate, what = notify_of[name]
                lst = cfg.approver_list(gate)
                if lst:
                    self.port.add_assignees(i["number"], lst)
                    if gate == "implementation":
                        how = ('Comment exactly "Approved" here to start it, or use Actions → '
                               '"Factory pipeline" → Run workflow (role: implementer, this issue number).')
                    elif gate == "release_scope":
                        how = ('Read the release plan above, then comment exactly "Approved" here to '
                               "release every issue in this milestone into intake.")
                    elif gate == "release":
                        how = ("This is already merged onto the integration branch and green there "
                               "(FACTORY.md §6a) — the Release Manager's integration report above is the "
                               "evidence. Merge the promotion PR(s) it lists, in that order, via the GitHub "
                               "UI. G3 is deliberately not comment-approvable.")
                    else:
                        how = ("Review the linked PR, then merge it + apply the approved label, or "
                               'comment exactly "Approved" here.')
                    self.say(i["number"],
                             f"{' '.join('@' + u for u in lst)} — **{what}** is waiting on you. {how}")
            if name == PROFILE_KIND:
                r.role = "profiler"
                log.info("factory:profile applied - running the Profiler")
            if name == FAST_TRACK:
                other_states = [x for x in labels if x.startswith("factory:") and x != FAST_TRACK]
                in_flight = not all(
                    x in ["factory:backlog", "factory:intake", *ORTHOGONAL] for x in other_states)
                if in_flight:
                    self.say(i["number"],
                             f"`{FAST_TRACK}` was applied, but this issue is already at "
                             f"**{self.state_of(labels)}** — "
                             "the fast lane does not take over work the pipeline has started. Remove the label to "
                             "carry on, or close this issue and file the small change separately.")
                    log.info("Fast-track on an in-flight issue (%s) - not running",
                             ", ".join(other_states))
                elif self.fast_track_done(i["number"]):
                    log.info("Fast-track already opened a PR for this issue - not running again")
                else:
                    self.drop_label(i["number"], "factory:backlog")
                    self.drop_label(i["number"], "factory:intake")
                    r.role = "fasttrack"
                    log.info("factory:fast-track applied - running the fast lane")


def release_chain(port: RepoPort, release_issue: int) -> tuple[list[str], int]:
    """Port of the release-chain job: fan a gate-G0-approved milestone out."""
    tracker = port.get_issue(release_issue)
    if not tracker or "factory:release-approved" not in _names(tracker.get("labels")):
        log.info("Release #%s is not factory:release-approved - nothing to release.", release_issue)
        return [], 0
    mark = "<!-- factory-release-dispatched -->"
    comments = port.list_comments(release_issue)
    if any(mark in (c.get("body") or "") for c in comments):
        log.info("Release #%s was already dispatched - skipping.", release_issue)
        return [], 0
    m = re.match(r"^release\((\d+)\):", tracker.get("title") or "")
    if not m:
        log.info("#%s does not name a milestone in its title - skipping.", release_issue)
        return [], 0
    members = port.list_issues(milestone=int(m.group(1)), state="open")
    started: list[int] = []
    skipped: list[str] = []
    for it in members:
        if it.get("pull_request") is not None:
            continue
        ls = _names(it.get("labels"))
        if "factory:release" in ls:
            continue
        if _is_task_title(it.get("title")):
            continue
        inflight = [x for x in ls if x.startswith("factory:") and x not in (
            "factory:backlog", "factory:intake", "factory:blocked", "factory:in-progress")]
        if inflight:
            skipped.append(f"#{it['number']} — already `{'`, `'.join(inflight)}`")
            continue
        if "factory:backlog" in ls:
            port.remove_label(it["number"], "factory:backlog")
        if "factory:intake" not in ls:
            port.add_labels(it["number"], ["factory:intake"])
        started.append(it["number"])
    title_rest = re.sub(r"^release\(\d+\):\s*", "", tracker.get("title") or "")
    lines = [f"**Gate G0 approved** — releasing milestone `{title_rest}`.", ""]
    if started:
        lines.append(f"{len(started)} issue(s) enter intake now:\n"
                     + "\n".join(f"- #{x} → `factory:intake`" for x in started))
    else:
        lines.append("_No backlog issues in this milestone — nothing to start._")
    if skipped:
        lines.extend(["", "Already in flight, left where they are:",
                      *[f"- {s}" for s in skipped]])
    lines.extend(["", "Issues added to this milestone from now on enter intake immediately.", "", mark])
    port.create_comment(release_issue, "\n".join(lines) + f"\n\n{AGENT_MARK}")
    log.info("Released %d issue(s) from milestone %s", len(started), m.group(1))
    return [str(x) for x in started], len(started)
