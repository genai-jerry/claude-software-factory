"""The promotion merge is gate G3 (FACTORY.md §4): a human merges the
Release Manager's promotion PR, and the epic is in production. Nothing in the
engine used to notice — the Release Manager's run had ended when it posted the
merge list — so a shipped epic sat at `factory:in-staging` with Compass still
asking whether to ship it. The merged `pull_request` event now moves the epic
and its tasks to `factory:deployed` and says what happens next, once every
repo's promotion PR is merged.
"""
from __future__ import annotations

from pathlib import Path

from factory_orchestrator.router import RepoConfig, Router

from .fake_repo import FakeRepo

FACTORY = Path(__file__).resolve().parents[2]


def issue(n, title, labels, body="", state="open"):
    return {"number": n, "title": title, "body": body, "state": state,
            "labels": [{"name": x} for x in labels], "user": {"type": "User"},
            "milestone": None}


def promotion_pr(number, title, head="staging", base="main", merged=True, body=""):
    return {"number": number, "title": title, "merged": merged, "body": body,
            "head": {"ref": head, "sha": "abc"}, "base": {"ref": base}}


def merged(world, pr, action="closed"):
    return {"action": action, "pull_request": pr,
            "repository": {"full_name": f"{world.owner}/{world.repo}", "default_branch": "main"}}


def api_repo(epic_labels=("factory:in-staging", "factory:expedite")):
    w = FakeRepo({
        34: issue(34, "Booker status on the sheet", list(epic_labels)),
        40: issue(40, "task(34): status map", ["factory:in-staging"]),
        41: issue(41, "task(34): the adapter writes", ["factory:in-staging"]),
        42: issue(42, "task(35): another epic's task", ["factory:in-staging"]),
    }, owner="o", repo="api")
    return w


def router(world, **kw):
    return Router(world, RepoConfig(), factory_checkout=FACTORY, **kw)


def test_a_merged_promotion_ships_the_epic_and_its_tasks():
    w = api_repo()
    r = router(w).route("pull_request", merged(w, promotion_pr(110, "release(34): promote staging to main")))
    assert r.role == "none"
    assert w.labels_of(34) == ["factory:expedite", "factory:deployed"]
    assert w.labels_of(40) == ["factory:deployed"]
    assert w.labels_of(41) == ["factory:deployed"]
    # Another epic's task is not this promotion's.
    assert w.labels_of(42) == ["factory:in-staging"]
    notice = w.comments[34][-1]["body"]
    assert "**Promotion** finished — #34 is now at `factory:deployed`." in notice
    assert "<!-- factory-next:factory:deployed -->" in notice
    assert "close this issue yourself" in notice


def test_every_epic_named_in_the_title_ships():
    w = api_repo()
    w.issues[35] = issue(35, "Second epic", ["factory:in-staging"])
    router(w).route("pull_request", merged(w, promotion_pr(110, "release(34, 35, 36): promote staging to main")))
    assert w.labels_of(34) == ["factory:expedite", "factory:deployed"]
    assert w.labels_of(35) == ["factory:deployed"]
    assert w.labels_of(42) == ["factory:deployed"]


def test_only_a_merged_promotion_pr_routes():
    for pr, action in [
        (promotion_pr(110, "release(34): promote staging to main", merged=False), "closed"),
        (promotion_pr(110, "release(34): promote staging to main"), "opened"),
        (promotion_pr(110, "release(34): promote staging to main", base="staging", head="factory/epic-34"), "closed"),
        (promotion_pr(110, "feat(34): something else", head="staging"), "closed"),
    ]:
        w = api_repo()
        router(w).route("pull_request", merged(w, pr, action))
        assert w.labels_of(34) == ["factory:in-staging", "factory:expedite"], pr["title"]
        assert 34 not in w.comments


def test_an_epic_that_already_shipped_is_left_alone():
    w = api_repo(epic_labels=("factory:deployed",))
    router(w).route("pull_request", merged(w, promotion_pr(110, "release(34): promote staging to main")))
    assert w.labels_of(34) == ["factory:deployed"]
    assert 34 not in w.comments


def test_the_epic_waits_for_a_sibling_repos_promotion():
    api = api_repo()
    web = FakeRepo({34: issue(34, "An unrelated web issue", ["factory:ready"])}, owner="o", repo="web")
    web.open_prs["any"] = [{"number": 38, "title": "release(34): promote staging to main",
                            "body": "Ships o/api#34.", "head": {"ref": "staging"}, "base": {"ref": "main"}}]
    ports = {("o", "api"): api, ("o", "web"): web}
    estate = ["o/api", "o/web"]

    # beacon-api's promotion merges first: the epic is told, not moved.
    Router(api, RepoConfig(), port_for=lambda o, n: ports[(o, n)], estate=estate,
           factory_checkout=FACTORY).route(
        "pull_request", merged(api, promotion_pr(110, "release(34): promote staging to main")))
    assert api.labels_of(34) == ["factory:in-staging", "factory:expedite"]
    assert "api is in production" in api.comments[34][-1]["body"]
    assert "ships from web" in api.comments[34][-1]["body"]

    # Then the web promotion merges: its own #34 is not an epic, the body
    # names the real one, and now nothing is open anywhere.
    web.open_prs["any"] = []
    Router(web, RepoConfig(), port_for=lambda o, n: ports[(o, n)], estate=estate,
           factory_checkout=FACTORY).route(
        "pull_request", merged(web, promotion_pr(38, "release(34): promote staging to main",
                                                 body="Ships o/api#34.")))
    assert web.labels_of(34) == ["factory:ready"]
    assert api.labels_of(34) == ["factory:expedite", "factory:deployed"]
    assert api.labels_of(40) == ["factory:deployed"]
    assert "<!-- factory-next:factory:deployed -->" in api.comments[34][-1]["body"]


def test_a_sibling_promotion_without_the_full_reference_does_not_guess():
    api = api_repo()
    web = FakeRepo({34: issue(34, "An unrelated web issue", ["factory:in-staging"])}, owner="o", repo="web")
    ports = {("o", "api"): api, ("o", "web"): web}
    Router(web, RepoConfig(), port_for=lambda o, n: ports[(o, n)], estate=["o/api", "o/web"],
           factory_checkout=FACTORY).route(
        "pull_request", merged(web, promotion_pr(38, "release(34): promote staging to main", body="")))
    # web's own #34 is an in-staging issue, so it ships — api's is not named.
    assert web.labels_of(34) == ["factory:deployed"]
    assert api.labels_of(34) == ["factory:in-staging", "factory:expedite"]
