"""A person's question about a thread, answered by a read-only Claude session."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import base64

from factory_orchestrator.ask import ASK_TOOLS, MODES, AskError, answer_question, check_images
from factory_orchestrator.config import load_config
from factory_orchestrator.ledger import Ledger
from factory_orchestrator.repo_cache import RepoCache
from factory_orchestrator.role_runner import FactorySource, RoleRunner
from factory_orchestrator.webhook import create_app

from .fake_repo import FakeRepo
from .test_config import BASE
from .test_role_runner import (
    make_bare_origin,
    make_consuming_repo,
    make_fake_claude,
    make_local_factory,
)

RESULT = ('{"type":"result","result":"It stopped after two rework rounds. Reply on #11 to allow one more.",'
          '"is_error":false,"num_turns":3,"total_cost_usd":0.03,'
          '"usage":{"input_tokens":120,"output_tokens":40}}')


def engine_for(tmp_path, on_run=RESULT, env=None):
    cfg = load_config({**BASE, "ROLE_TIMEOUT_SECONDS": "60", **(env or {})})
    source = FactorySource(cfg, local_path=str(make_local_factory(tmp_path)))
    origin = make_bare_origin(make_consuming_repo(tmp_path), tmp_path / "r.git")
    cache = RepoCache(str(tmp_path / "cache"), url_for=lambda o, r, t: str(origin),
                      env={"PATH": os.environ["PATH"], "GIT_TERMINAL_PROMPT": "0"})
    (tmp_path / "ws").mkdir()
    out = tmp_path / "captured"
    claude = make_fake_claude(tmp_path, out, on_run=f"echo '{on_run}'\n" if on_run else None)
    runner = RoleRunner(cfg, source, workspace_root=str(tmp_path / "ws"),
                        claude_bin=str(claude), repo_cache=cache)
    engine = SimpleNamespace(
        cfg=cfg, runner=runner, probe=lambda m: True,
        port=lambda o, r: FakeRepo(owner=o, repo=r),
        app=SimpleNamespace(installation_token=lambda *a, **k: "ghs_secret"))
    return engine, out


def test_a_question_is_answered_in_a_read_only_session(tmp_path):
    engine, out = engine_for(tmp_path)
    got = answer_question(engine, owner="o", repo="r", question="Why is #11 blocked?",
                          context="[agent] Reviewer: round 2 blocked.")
    assert got["answer"].startswith("It stopped after two rework rounds.")
    assert got["usage"] == {"input_tokens": 120, "output_tokens": 40, "cost_usd": 0.03}
    argv = next(out.glob("argv-*.txt")).read_text().split("\n")
    assert argv[argv.index("--allowedTools") + 1] == ASK_TOOLS
    assert "--output-format" in argv and "Write" not in ASK_TOOLS and "Edit" not in ASK_TOOLS
    prompt = next(out.glob("prompt-*.txt")).read_text()
    assert "Why is #11 blocked?" in prompt and "round 2 blocked" in prompt
    # no GitHub token reaches the session, and its checkout is gone afterwards
    assert "GH_TOKEN=\n" in next(out.glob("env-*.txt")).read_text() + "\n"
    assert not list((tmp_path / "ws").iterdir())


def test_the_default_answer_follows_the_writing_standard(tmp_path):
    engine, out = engine_for(tmp_path)
    answer_question(engine, owner="o", repo="r", question="why?", context="thread")
    prompt = next(out.glob("prompt-*.txt")).read_text()
    for rule in ("15 words or fewer", "You need to:", "at most 5 bullets", "120 words", "active voice"):
        assert rule in prompt, rule


def test_the_callers_instructions_replace_the_default_style(tmp_path):
    engine, out = engine_for(tmp_path)
    answer_question(engine, owner="o", repo="r", question="why?", context="[1] a source",
                    instructions="Cite sources as [n].")
    prompt = next(out.glob("prompt-*.txt")).read_text()
    assert "Cite sources as [n]." in prompt and "at most 150 words" not in prompt
    assert "[1] a source" in prompt


def test_an_empty_question_or_missing_credential_is_refused(tmp_path):
    engine, _ = engine_for(tmp_path)
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="r", question="  ", context="")
    assert e.value.status == 400
    engine.cfg = SimpleNamespace(agent_credential_env=lambda: {})
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="r", question="why?", context="")
    assert e.value.status == 503 and "credential" in str(e.value)


def test_a_usage_limit_is_named(tmp_path):
    engine, _ = engine_for(tmp_path, on_run="You've hit your session limit · resets 2:50pm (UTC)")
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="r", question="why?", context="")
    assert e.value.status == 429 and "usage limit" in str(e.value)


async def test_the_endpoint_needs_the_operator_token_and_returns_the_answer(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db", "DISPATCH_TOKEN": "op-token"})
    app = create_app(cfg, Ledger(cfg.database_url), lambda *_: None, poll_interval=0.05)
    seen = {}

    def asker(**kw):
        seen.update(kw)
        return {"answer": "Because of the cap.", "model": "m", "usage": {}}
    app.state.asker = asker
    body = {"owner": "o", "repo": "r", "question": "why?", "context": "thread", "branch": "factory/epic-34",
            "instructions": "Cite sources as [n]."}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.post("/ask", json=body)).status_code == 401
        ok = await c.post("/ask", json=body, headers={"authorization": "Bearer op-token"})
        assert ok.status_code == 200 and ok.json()["answer"] == "Because of the cap."
        bad = await c.post("/ask", json={"owner": "o"}, headers={"authorization": "Bearer op-token"})
        assert bad.status_code == 400
    assert seen["branch"] == "factory/epic-34" and seen["question"] == "why?"
    assert seen["instructions"] == "Cite sources as [n]."


PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40).decode()


def test_images_land_beside_the_checkout_and_are_named_in_the_prompt(tmp_path):
    # The fake claude lists what it finds where the prompt says to look.
    listing = tmp_path / "attachments.txt"
    engine, out = engine_for(tmp_path)
    (tmp_path / "claude-hook.sh").write_text(f"ls \"$HOME/attachments\" > {listing}\necho '{RESULT}'\n")
    answer_question(engine, owner="o", repo="r", question="What is on this screen?", context="",
                    images=[{"name": "leads page.png", "mime": "image/png", "data_b64": PNG},
                            {"name": "../../etc/passwd", "mime": "image/jpeg", "data_b64": PNG}])
    prompt = next(out.glob("prompt-*.txt")).read_text()
    assert "attached 2 images" in prompt and "Read each one with the Read tool" in prompt
    assert "/attachments/1-leads-page.png" in prompt and "/attachments/2-passwd.jpg" in prompt
    assert sorted(listing.read_text().split()) == ["1-leads-page.png", "2-passwd.jpg"]
    # The checkout itself carries no attachment, and everything is gone afterwards.
    assert "r/attachments" not in prompt
    assert not list((tmp_path / "ws").iterdir())


def test_shape_mode_has_wider_budgets_and_the_same_read_only_tools(tmp_path):
    engine, out = engine_for(tmp_path)
    long_question = "Shape this. " * 400  # ~4 800 chars: over ask's 2 000, under shape's 12 000
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="r", question=long_question, context="")
    assert e.value.status == 400 and "2000" in str(e.value)
    answer_question(engine, owner="o", repo="r", question=long_question, context="", mode="shape")
    argv = next(out.glob("argv-*.txt")).read_text().split("\n")
    assert argv[argv.index("--max-turns") + 1] == str(MODES["shape"][2])
    assert argv[argv.index("--allowedTools") + 1] == ASK_TOOLS
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="r", question="x", context="", mode="paint")
    assert e.value.status == 400


def test_a_bad_image_is_refused_before_anything_runs(tmp_path):
    engine, out = engine_for(tmp_path)
    for images, said in (
        ([{"name": "a.svg", "mime": "image/svg+xml", "data_b64": PNG}], "not supported"),
        ([{"name": "a.png", "mime": "image/png", "data_b64": "not base64!"}], "not valid base64"),
        ([{"name": "a.png", "mime": "image/png", "data_b64": PNG}] * 7, "At most 6"),
    ):
        with pytest.raises(AskError) as e:
            answer_question(engine, owner="o", repo="r", question="x", context="", images=images)
        assert e.value.status == 400 and said in str(e.value), said
    big = base64.b64encode(b"\x00" * (5 * 1024 * 1024 + 1)).decode()
    with pytest.raises(AskError) as e:
        check_images([{"name": "a.png", "mime": "image/png", "data_b64": big}])
    assert e.value.status == 400 and "over 5 MB" in str(e.value)
    assert not list(out.glob("prompt-*.txt"))


def test_an_ask_is_entered_in_the_ledger_as_a_finished_run(tmp_path):
    engine, _ = engine_for(tmp_path)
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db"})
    engine.ledger = Ledger(cfg.database_url)
    answer_question(engine, owner="o", repo="r", question="why?", context="", mode="shape")
    runs = engine.ledger.list_runs(repo="o/r")
    assert len(runs) == 1 and runs[0]["role"] == "ask" and runs[0]["outcome"] == "success"
    assert runs[0]["finished_at"] is not None
    assert not engine.ledger.list_runs(repo="o/r", active_only=True)
    import json
    assert json.loads(runs[0]["guards"])["usage"]["input_tokens"] == 120


async def test_the_endpoint_validates_images_and_passes_mode(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db", "DISPATCH_TOKEN": "op-token"})
    app = create_app(cfg, Ledger(cfg.database_url), lambda *_: None, poll_interval=0.05)
    seen = {}

    def asker(**kw):
        seen.update(kw)
        return {"answer": "A leads table.", "model": "m", "usage": {}}
    app.state.asker = asker
    h = {"authorization": "Bearer op-token"}
    body = {"owner": "o", "repo": "r", "question": "what is this?", "mode": "shape",
            "images": [{"name": "s.png", "mime": "image/png", "data_b64": PNG}]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        ok = await c.post("/ask", json=body, headers=h)
        assert ok.status_code == 200, ok.text
        bad = await c.post("/ask", json={**body, "images": [{"name": "s.svg", "mime": "image/svg+xml", "data_b64": PNG}]}, headers=h)
        assert bad.status_code == 400 and "not supported" in bad.json()["detail"]
        worse = await c.post("/ask", json={**body, "mode": "draw"}, headers=h)
        assert worse.status_code == 400
    assert seen["mode"] == "shape" and seen["images"][0]["name"] == "s.png"


def test_sibling_repositories_are_checked_out_beside_the_primary(tmp_path):
    # The fake claude lists the home: the primary and each sibling sit side by side.
    listing = tmp_path / "home.txt"
    engine, out = engine_for(tmp_path)
    (tmp_path / "claude-hook.sh").write_text(f"ls \"$HOME\" > {listing}\necho '{RESULT}'\n")
    answer_question(engine, owner="o", repo="r", question="Where does the web read this?", context="",
                    repos=[{"owner": "o", "repo": "web", "branch": "factory/epic-35"},
                           {"owner": "o", "repo": "r", "branch": None},  # the primary: dropped
                           {"owner": "o", "repo": "connectors", "branch": None}])
    prompt = next(out.glob("prompt-*.txt")).read_text()
    assert "Other repositories of this project are checked out beside it" in prompt
    # The test origin has no factory/epic-35, so the sibling falls back to its default branch.
    assert "`../web` (on `" in prompt and "`../connectors` (on `" in prompt
    assert "factory/epic-35" not in prompt
    argv = next(out.glob("argv-*.txt")).read_text().split("\n")
    dirs = [argv[i + 1] for i, a in enumerate(argv) if a == "--add-dir"]
    assert [Path(d).name for d in dirs] == ["web", "connectors"]
    assert sorted(x for x in listing.read_text().split() if x != "attachments") == ["connectors", "r", "web"]
    assert not list((tmp_path / "ws").iterdir())


def test_a_sibling_that_cannot_be_reached_is_named_not_fatal(tmp_path):
    engine, out = engine_for(tmp_path)

    def token_for(owner, repo, **_):
        if repo == "broken":
            raise RuntimeError("no installation covers o/broken")
        return "ghs_secret"
    engine.app = SimpleNamespace(installation_token=token_for)
    got = answer_question(engine, owner="o", repo="r", question="why?", context="",
                          repos=[{"owner": "o", "repo": "broken", "branch": None},
                                 {"owner": "o", "repo": "web", "branch": None}])
    assert got["answer"].startswith("It stopped")
    prompt = next(out.glob("prompt-*.txt")).read_text()
    assert "Not available this time" in prompt and "`broken`" in prompt
    assert "`../web` (on `" in prompt
    argv = next(out.glob("argv-*.txt")).read_text().split("\n")
    assert sum(1 for a in argv if a == "--add-dir") == 1


def test_bad_sibling_lists_are_refused_before_anything_runs(tmp_path):
    engine, out = engine_for(tmp_path)
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="r", question="x", context="",
                        repos=[{"owner": "o", "repo": f"s{i}"} for i in range(9)])
    assert e.value.status == 400 and "At most 8" in str(e.value)
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="r", question="x", context="", repos=[{"owner": "o"}])
    assert e.value.status == 400
    assert not list(out.glob("argv-*.txt"))


async def test_the_endpoint_validates_repos(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db", "DISPATCH_TOKEN": "op-token"})
    app = create_app(cfg, Ledger(cfg.database_url), lambda *_: None, poll_interval=0.05)
    seen = {}

    def asker(**kw):
        seen.update(kw)
        return {"answer": "ok", "model": "m", "usage": {}}
    app.state.asker = asker
    h = {"authorization": "Bearer op-token"}
    body = {"owner": "o", "repo": "r", "question": "x", "repos": [{"owner": "o", "repo": "web", "branch": "main"}]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        ok = await c.post("/ask", json=body, headers=h)
        assert ok.status_code == 200, ok.text
        bad = await c.post("/ask", json={**body, "repos": "web"}, headers=h)
        assert bad.status_code == 400
        many = await c.post("/ask", json={**body, "repos": [{"owner": "o", "repo": f"s{i}"} for i in range(9)]}, headers=h)
        assert many.status_code == 400 and "At most 8" in many.json()["detail"]
    assert seen["repos"] == [{"owner": "o", "repo": "web", "branch": "main"}]


SESSION_RESULT = RESULT[:-1] + ',"session_id":"sess-1"}'


def test_a_conversation_keeps_its_workspace_and_brings_it_level(tmp_path):
    engine, out = engine_for(tmp_path, on_run=SESSION_RESULT)
    cache = engine.runner.repo_cache
    clones = []
    real_checkout = cache.checkout
    cache.checkout = lambda *a, **k: (clones.append(a[1]), real_checkout(*a, **k))[1]
    first = answer_question(engine, owner="o", repo="r", question="Where is the dialer?", context="",
                            conversation="idea-1", repos=[{"owner": "o", "repo": "web", "branch": None}])
    home = tmp_path / "ws" / "ask" / "idea-1"
    assert first["session"] == "sess-1" and first["resumed"] is False
    assert (home / "r" / ".git").exists() and (home / "web" / ".git").exists()
    assert clones == ["r", "web"]
    # GitHub moves on between messages: a new commit on the origin.
    work = tmp_path / "origin" / "r"
    (work / "NEW.md").write_text("new\n")
    env = {"PATH": os.environ["PATH"], "GIT_TERMINAL_PROMPT": "0", "HOME": str(tmp_path)}
    import subprocess
    subprocess.run(["git", "add", "NEW.md"], cwd=work, check=True, env=env)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "new"],
                   cwd=work, check=True, env=env)
    subprocess.run(["git", "push", "-q", str(tmp_path / "r.git"), "HEAD"], cwd=work, check=True, env=env)
    # A stray local change in the copy must not survive either.
    (home / "r" / "scratch.txt").write_text("x")
    second = answer_question(engine, owner="o", repo="r", question="And the web?", context="",
                             conversation="idea-1", repos=[{"owner": "o", "repo": "web", "branch": None}])
    assert clones == ["r", "web"], "the second message reuses the copies instead of cloning"
    assert (home / "r" / "NEW.md").exists() and not (home / "r" / "scratch.txt").exists()
    assert second["answer"].startswith("It stopped")
    # No remote, so no token, survives in either copy.
    for name in ("r", "web"):
        remotes = subprocess.run(["git", "remote"], cwd=home / name, capture_output=True, text=True).stdout
        assert remotes.strip() == ""
    # A throwaway ask still leaves nothing behind beside the conversation homes.
    answer_question(engine, owner="o", repo="r", question="once more", context="")
    assert sorted(p.name for p in (tmp_path / "ws").iterdir()) == ["ask"]


def test_a_session_is_resumed_with_only_the_new_question(tmp_path):
    engine, out = engine_for(tmp_path, on_run=SESSION_RESULT)
    answer_question(engine, owner="o", repo="r", question="first", context="long transcript",
                    conversation="idea-2")
    got = answer_question(engine, owner="o", repo="r", question="second question", context="ignored",
                          conversation="idea-2", session="sess-1",
                          images=[{"name": "shot.png", "mime": "image/png", "data_b64": PNG}])
    assert got["resumed"] is True and got["session"] == "sess-1"
    argvs = sorted(out.glob("argv-*.txt"))
    prompts = sorted(out.glob("prompt-*.txt"))
    assert len(argvs) == 2
    last = argvs[-1].read_text().split("\n")
    assert last[last.index("--resume") + 1] == "sess-1"
    short = prompts[-1].read_text()
    assert "second question" in short and "attached 1 image" in short
    assert "ignored" not in short and "You answer a question" not in short
    assert "--resume" not in argvs[0].read_text()


def test_a_failed_resume_falls_back_to_a_fresh_prompt(tmp_path):
    engine, out = engine_for(tmp_path, on_run=SESSION_RESULT)
    answer_question(engine, owner="o", repo="r", question="first", context="", conversation="idea-3")
    # The fake refuses a resume the way the CLI does for an unknown session.
    (tmp_path / "claude-hook.sh").write_text(
        f"if grep -qx -- '--resume' \"$(ls -t {tmp_path / 'captured'}/argv-*.txt | head -1)\"; then\n"
        "  echo '{\"type\":\"result\",\"is_error\":true,\"result\":\"No conversation found with session ID: sess-1\"}'\n"
        "else\n"
        f"  echo '{SESSION_RESULT}'\n"
        "fi\n")
    got = answer_question(engine, owner="o", repo="r", question="second", context="the transcript",
                          conversation="idea-3", session="sess-1")
    assert got["resumed"] is False and got["answer"].startswith("It stopped")
    prompts = sorted(out.glob("prompt-*.txt"))
    assert len(prompts) == 3  # first, the refused resume, the fresh fallback
    assert "the transcript" in prompts[-1].read_text() and "You answer a question" in prompts[-1].read_text()


def test_idle_conversation_homes_are_pruned(tmp_path):
    from factory_orchestrator.ask import ASK_IDLE_SECONDS, prune_conversations
    engine, out = engine_for(tmp_path)
    base = tmp_path / "ws" / "ask"
    old, fresh = base / "old", base / "fresh"
    for d in (old, fresh):
        d.mkdir(parents=True)
    import time as _t
    stale = _t.time() - ASK_IDLE_SECONDS - 60
    os.utime(old, (stale, stale))
    assert prune_conversations(tmp_path / "ws") == 1
    assert not old.exists() and fresh.exists()
    # The next ask prunes on its way in.
    os.utime(fresh, (stale, stale))
    answer_question(engine, owner="o", repo="r", question="x", context="", conversation="idea-4")
    assert not fresh.exists() and (base / "idea-4").exists()


def test_a_bad_conversation_key_or_session_is_refused(tmp_path):
    engine, out = engine_for(tmp_path)
    for bad in ("../etc", "a b", "x" * 65, ""):
        with pytest.raises(AskError) as e:
            answer_question(engine, owner="o", repo="r", question="x", context="", conversation=bad)
        assert e.value.status == 400
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="r", question="x", context="", conversation="ok", session=" ")
    assert e.value.status == 400
    assert not list(out.glob("argv-*.txt"))


@pytest.mark.anyio
async def test_the_endpoint_validates_the_conversation_key_and_passes_the_session(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db", "DISPATCH_TOKEN": "op-token"})
    app = create_app(cfg, Ledger(cfg.database_url), lambda *_: None, poll_interval=0.05)
    seen = {}

    def asker(**kw):
        seen.update(kw)
        return {"answer": "ok", "model": "m", "usage": {}, "session": "sess-9", "resumed": True}
    app.state.asker = asker
    h = {"authorization": "Bearer op-token"}
    base = {"owner": "o", "repo": "r", "question": "why?"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        bad = await c.post("/ask", json={**base, "conversation": "../x"}, headers=h)
        assert bad.status_code == 400 and "conversation" in bad.json()["detail"]
        ok = await c.post("/ask", json={**base, "conversation": "idea_1", "session": "sess-9"}, headers=h)
        assert ok.status_code == 200 and ok.json()["session"] == "sess-9" and ok.json()["resumed"] is True
    assert seen["conversation"] == "idea_1" and seen["session"] == "sess-9"


def test_a_repo_the_orchestrator_cannot_read_is_a_clear_refusal_not_a_crash(tmp_path):
    from factory_orchestrator.github_app import TokenUnavailableError
    engine, _ = engine_for(tmp_path)

    def no_token(*a, **k):
        raise TokenUnavailableError("no usable GitHub installation token for o/view")
    engine.app = SimpleNamespace(installation_token=no_token)
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="o", repo="view", question="What is needed here?", context="")
    assert e.value.status == 503
    assert "cannot read o/view" in str(e.value) and "GitHub Actions" in str(e.value)


async def test_an_unexpected_failure_says_what_kind_instead_of_a_bare_500(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db", "DISPATCH_TOKEN": "op-token"})
    app = create_app(cfg, Ledger(cfg.database_url), lambda *_: None, poll_interval=0.05)

    def asker(**kw):
        raise KeyError("ghs_secret_should_not_leak")
    app.state.asker = asker
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/ask", json={"owner": "o", "repo": "r", "question": "why?"},
                         headers={"authorization": "Bearer op-token"})
    assert r.status_code == 500
    assert r.json()["detail"] == "The orchestrator failed while answering (KeyError). Its log has the details."


def test_shape_about_a_new_product_runs_without_a_repository(tmp_path):
    engine, out = engine_for(tmp_path)

    def no_token(*a, **k):
        raise AssertionError("a new product needs no GitHub token")
    engine.app.installation_token = no_token
    engine.port = lambda o, r: (_ for _ in ()).throw(AssertionError("no repo to read config from"))
    got = answer_question(engine, owner="", repo="", question="A translator app for Malayalam?",
                          context="", mode="shape", conversation="c-new")
    assert got["answer"]
    cwd = Path(next(out.glob("cwd-*.txt")).read_text().strip())
    assert cwd.name == "idea" and not (cwd / ".git").exists()
    prompt = next(out.glob("prompt-*.txt")).read_text()
    assert "There is no repository" in prompt and "Repository:" not in prompt
    assert "except\nthrough the organisation's tools" in prompt


def test_only_shape_may_run_without_a_repository(tmp_path):
    engine, _ = engine_for(tmp_path)
    with pytest.raises(AskError) as e:
        answer_question(engine, owner="", repo="", question="why?", context="")
    assert e.value.status == 400
    with pytest.raises(AskError):
        answer_question(engine, owner="", repo="", question="x", context="", mode="shape",
                        repos=[{"owner": "o", "repo": "web"}])


async def test_the_endpoint_takes_owner_and_repo_together_or_neither(tmp_path):
    cfg = load_config({**BASE, "DATABASE_URL": f"sqlite:///{tmp_path}/o.db", "DISPATCH_TOKEN": "op-token"})
    app = create_app(cfg, Ledger(cfg.database_url), lambda *_: None, poll_interval=0.05)
    seen = {}

    def asker(**kw):
        seen.update(kw)
        return {"answer": "ok", "model": "m", "usage": {}}
    app.state.asker = asker
    h = {"authorization": "Bearer op-token"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        ok = await c.post("/ask", json={"question": "new idea", "mode": "shape"}, headers=h)
        assert ok.status_code == 200, ok.text
        assert seen["owner"] == "" and seen["repo"] == ""
        half = await c.post("/ask", json={"owner": "o", "question": "x"}, headers=h)
        assert half.status_code == 400
