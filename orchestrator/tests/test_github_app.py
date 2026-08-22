import base64
import hashlib
import hmac
import json

import httpx

from factory_orchestrator.config import load_config
from factory_orchestrator.github_app import GitHubApp, parse_json_or_empty, verify_signature

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
