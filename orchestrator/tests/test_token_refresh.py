"""The orchestrator half of the Console's token-mint endpoint."""

import httpx
import pytest

from factory_orchestrator.token_refresh import ConsoleTokenSource, TokenRefreshError


def source(handler, *, dispatch_token="op-token"):
    return ConsoleTokenSource(
        dispatch_token, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_mint_posts_the_installation_id_with_the_dispatch_token():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"token": "ghs_new",
                                         "expires_at": "2026-08-29T10:05:01Z"})

    src = source(handler)
    src.register("o", "r", "https://console.example/", 4242)
    assert src.mint("o", "r") == ("ghs_new", "2026-08-29T10:05:01Z")
    assert seen["url"] == "https://console.example/api/orchestrator/github-token"
    assert seen["auth"] == "Bearer op-token"


def test_a_repo_nobody_registered_cannot_be_refreshed():
    src = source(lambda r: httpx.Response(200, json={"token": "x"}))
    assert not src.can_refresh("o", "r")
    with pytest.raises(TokenRefreshError) as e:
        src.mint("o", "r")
    assert "console_url and installation_id" in str(e.value)


def test_half_a_route_registers_nothing():
    src = source(lambda r: httpx.Response(200, json={"token": "x"}))
    src.register("o", "r", "https://console.example", None)
    src.register("o", "r", None, 4242)
    assert not src.can_refresh("o", "r")


def test_without_a_dispatch_token_the_console_cannot_be_asked():
    src = source(lambda r: httpx.Response(200, json={"token": "x"}), dispatch_token="")
    src.register("o", "r", "https://console.example", 4242)
    assert not src.can_refresh("o", "r")
    with pytest.raises(TokenRefreshError) as e:
        src.mint("o", "r")
    assert "DISPATCH_TOKEN" in str(e.value)


def test_a_console_error_says_what_the_console_said():
    src = source(lambda r: httpx.Response(503, json={"error": "GitHub App is not configured"}))
    src.register("o", "r", "https://console.example", 4242)
    with pytest.raises(TokenRefreshError) as e:
        src.mint("o", "r")
    assert "503" in str(e.value) and "GitHub App is not configured" in str(e.value)


def test_an_unreachable_console_is_reported_as_such():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    src = source(handler)
    src.register("o", "r", "https://console.example", 4242)
    with pytest.raises(TokenRefreshError) as e:
        src.mint("o", "r")
    assert "could not reach the Console" in str(e.value)


def test_a_response_without_a_token_is_not_treated_as_one():
    src = source(lambda r: httpx.Response(200, json={"expires_at": "2026-08-29T10:05:01Z"}))
    src.register("o", "r", "https://console.example", 4242)
    with pytest.raises(TokenRefreshError) as e:
        src.mint("o", "r")
    assert "returned no token" in str(e.value)
