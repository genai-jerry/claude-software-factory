import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from factory_orchestrator.config import load_config
from factory_orchestrator.github_app import (
    GitHubApp,
    TokenUnavailableError,
    parse_expiry,
    parse_json_or_empty,
    verify_signature,
)
from factory_orchestrator.token_refresh import ConsoleTokenSource

from .test_config import BASE


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signature_roundtrip():
    body = b'{"a": 1}'
    assert verify_signature("s3cret", body, sign("s3cret", body))
    assert not verify_signature("s3cret", body, sign("wrong", body))
    assert not verify_signature("s3cret", body, None)
    assert not verify_signature("s3cret", body, "sha1=abc")


def test_parse_json_or_empty():
    assert parse_json_or_empty(None) == {}
    assert parse_json_or_empty("{not json") == {}
    assert parse_json_or_empty('["list"]') == {}
    assert parse_json_or_empty('{"engine": "langgraph"}') == {"engine": "langgraph"}


def make_app(handler) -> GitHubApp:
    cfg = load_config(BASE)
    client = httpx.Client(transport=httpx.MockTransport(handler),
                          base_url="https://api.github.com")
    app = GitHubApp(cfg, client)
    # Bypass RS256 signing (the test key is not a real RSA key) — token
    # minting itself is exercised through the mocked endpoints.
    app.app_jwt = lambda: "test-jwt"  # type: ignore[method-assign]
    return app


def github_stub(state):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        state["calls"].append((request.method, path))
        if path == "/repos/o/r/installation":
            return httpx.Response(200, json={"id": 42})
        if path == "/app/installations/42/access_tokens":
            state["minted"] += 1
            return httpx.Response(201, json={"token": f"ghs_tok{state['minted']}"})
        if path == "/repos/o/r/issues/5/labels" and request.method == "POST":
            state["labels"] += json.loads(request.content)["labels"]
            return httpx.Response(200, json=[])
        if path.startswith("/repos/o/r/issues/5/labels/") and request.method == "DELETE":
            return httpx.Response(404, json={"message": "not found"})
        if path == "/repos/o/r/contents/.github/factory-orchestrator.json":
            content = base64.b64encode(b'{"engine": "langgraph"}').decode()
            return httpx.Response(200, json={"encoding": "base64", "content": content})
        if path == "/repos/o/r/contents/missing.json":
            return httpx.Response(404, json={"message": "nope"})
        if path == "/repos/o/r/issues" and request.method == "GET":
            return httpx.Response(200, json=[{"number": 1}])
        return httpx.Response(500, json={"path": path})
    return handler


def test_installation_token_cached_per_repo():
    state = {"calls": [], "minted": 0, "labels": []}
    app = make_app(github_stub(state))
    t1 = app.installation_token("o", "r")
    t2 = app.installation_token("o", "r")
    assert t1 == t2 == "ghs_tok1"
    assert state["minted"] == 1


def test_repo_client_basics():
    state = {"calls": [], "minted": 0, "labels": []}
    app = make_app(github_stub(state))
    rc = app.repo_client("o", "r")
    rc.add_labels(5, ["factory:intake"])
    assert state["labels"] == ["factory:intake"]
    # 404 on label removal is swallowed, matching the JS router's catch.
    rc.remove_label(5, "factory:backlog")
    assert rc.get_file(".github/factory-orchestrator.json") == '{"engine": "langgraph"}'
    assert rc.get_file("missing.json") is None
    assert rc.list_issues() == [{"number": 1}]


# --------------------------------------------------------------- token life
PLACEHOLDER = {**BASE, "GITHUB_APP_ID": "000000", "GITHUB_APP_PRIVATE_KEY": "placeholder"}


def test_cache_token_honours_a_real_expiry():
    """A Console token is only as good as its own clock, not our arrival time."""
    state = {"calls": [], "minted": 0, "labels": []}
    app = make_app(github_stub(state))
    past = datetime.now(UTC) - timedelta(minutes=5)
    app.cache_token("o", "r", "ghs_console", expires_at=past.isoformat())
    # Expired on arrival: the next caller must not be handed it.
    assert app.installation_token("o", "r") == "ghs_tok1"
    assert state["minted"] == 1


def test_cache_token_without_an_expiry_assumes_little():
    """Unknown expiry used to mean 50 minutes of misplaced confidence."""
    state = {"calls": [], "minted": 0, "labels": []}
    app = make_app(github_stub(state))
    app.cache_token("o", "r", "ghs_console")
    assert app.token_remaining("o", "r") <= 30 * 60 + 1
    # Good enough for an ordinary call...
    assert app.installation_token("o", "r") == "ghs_console"
    # ...but not for a role that may run the better part of an hour.
    assert app.installation_token("o", "r", min_remaining=45 * 60) == "ghs_tok1"


def test_min_remaining_is_capped_rather_than_unsatisfiable():
    """Nobody can hand out more than a token's lifetime; warn, don't fail."""
    state = {"calls": [], "minted": 0, "labels": []}
    app = make_app(github_stub(state))
    assert app.installation_token("o", "r", min_remaining=10 * 60 * 60) == "ghs_tok1"


def test_401_is_retried_once_with_a_fresh_token():
    """The failure that ended run 3c2bf884: a role outlives its token and the
    closing GET /issues/{n} 401s. One re-mint makes it invisible."""
    state = {"calls": [], "minted": 0, "labels": [], "seen": []}
    stub = github_stub(state)

    def handler(request):
        if request.url.path == "/repos/o/r/issues/227":
            state["seen"].append(request.headers["authorization"])
            # The token minted first is the stale one the role started with.
            if state["seen"][-1] == "token ghs_tok1":
                return httpx.Response(401, json={"message": "Bad credentials"})
            return httpx.Response(200, json={"number": 227})
        return stub(request)

    app = make_app(handler)
    rc = app.repo_client("o", "r")
    assert rc.get_issue(227) == {"number": 227}
    assert state["seen"] == ["token ghs_tok1", "token ghs_tok2"]
    assert state["minted"] == 2


def test_401_that_survives_a_refresh_still_raises():
    """A real permission problem must not be retried into silence."""
    state = {"calls": [], "minted": 0, "labels": []}
    stub = github_stub(state)

    def handler(request):
        if request.url.path == "/repos/o/r/issues/9":
            return httpx.Response(401, json={"message": "Bad credentials"})
        return stub(request)

    app = make_app(handler)
    with pytest.raises(httpx.HTTPStatusError) as e:
        app.repo_client("o", "r").get_issue(9)
    assert e.value.response.status_code == 401
    assert state["minted"] == 2  # tried once more before giving up


def test_placeholder_deployment_refreshes_through_the_console():
    """The lighthouse-style deployment has no App key; the Console mints for it."""
    calls = []

    def console_handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={
            "token": "ghs_from_console",
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        })

    cfg = load_config(PLACEHOLDER)
    console = ConsoleTokenSource(
        "dispatch-secret",
        client=httpx.Client(transport=httpx.MockTransport(console_handler)))
    console.register("o", "r", "https://console.example", 4242)
    app = GitHubApp(cfg, httpx.Client(base_url="https://api.github.com"), console=console)

    assert not app.can_mint()
    assert app.installation_token("o", "r", min_remaining=45 * 60) == "ghs_from_console"
    assert calls == [{"installation_id": 4242}]
    # The real expiry came back with it, so the next caller can trust it.
    assert app.token_remaining("o", "r") > 50 * 60


def test_no_token_source_gives_an_operator_an_actionable_error():
    """`401 Unauthorized` on a run record tells nobody what to do about it."""
    cfg = load_config(PLACEHOLDER)
    app = GitHubApp(cfg, httpx.Client(base_url="https://api.github.com"),
                    console=ConsoleTokenSource("dispatch-secret"))
    with pytest.raises(TokenUnavailableError) as e:
        app.installation_token("o", "r")
    message = str(e.value)
    assert "console_url" in message and "installation_id" in message


def test_an_unrefreshable_token_is_still_used_while_it_lives():
    """Losing the ability to re-mint must not throw away a working token."""
    cfg = load_config(PLACEHOLDER)
    app = GitHubApp(cfg, httpx.Client(base_url="https://api.github.com"),
                    console=ConsoleTokenSource(""))
    app.cache_token("o", "r", "ghs_console")
    # Wants more life than is left and cannot get it: the held token still works.
    assert app.installation_token("o", "r", min_remaining=45 * 60) == "ghs_console"


def test_parse_expiry_tolerates_what_github_and_operators_send():
    assert parse_expiry(None) is None
    assert parse_expiry("not a date") is None
    stamped = datetime(2026, 8, 29, 9, 5, 1, tzinfo=UTC)
    # GitHub sends "Z"; a naive string from an operator means UTC too.
    assert parse_expiry("2026-08-29T09:05:01Z") == stamped.timestamp()
    assert parse_expiry("2026-08-29T09:05:01") == stamped.timestamp()
