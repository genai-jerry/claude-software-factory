import pytest

from factory_orchestrator.models import (
    DEFAULT_CHAIN,
    ModelResolutionError,
    chain_for,
    resolve_model,
)


def probe_allowing(*models):
    calls = []

    def probe(m):
        calls.append(m)
        return m in models
    probe.calls = calls
    return probe


def test_first_accessible_wins():
    r = resolve_model("intake", {"intake": ["big", "mid", "small"]}, probe_allowing("big"))
    assert r.model == "big" and r.fallbacks == []


def test_fallback_recorded():
    r = resolve_model("intake", {"intake": ["big", "mid", "small"]}, probe_allowing("small"))
    assert r.model == "small"
    assert r.fallbacks == ["big", "mid"]


def test_missing_role_uses_default_chain():
    probe = probe_allowing(*DEFAULT_CHAIN)
    r = resolve_model("reviewer", {}, probe)
    assert r.model == DEFAULT_CHAIN[0]
    assert probe.calls == [DEFAULT_CHAIN[0]]


def test_missing_role_falls_through_the_default_chain():
    # `ask` had no entry anywhere and the subscription could not use the one
    # default model, so every question failed. The default must reach a
    # model the credential has.
    probe = probe_allowing("claude-opus-5")
    r = resolve_model("ask", {"intake": ["claude-opus-5"]}, probe)
    assert r.model == "claude-opus-5"
    assert r.fallbacks == ["claude-sonnet-5"]


def test_string_chain_and_junk_config():
    assert chain_for("x", {"x": "solo"}) == ["solo"]
    assert chain_for("x", {"x": []}) == DEFAULT_CHAIN
    assert chain_for("x", {"x": [1, 2]}) == DEFAULT_CHAIN


def test_exhausted_chain_raises():
    with pytest.raises(ModelResolutionError, match="factory-models.json"):
        resolve_model("intake", {"intake": ["a", "b"]}, probe_allowing())


# --- Compass → Models -------------------------------------------------------

import httpx  # noqa: E402

from factory_orchestrator.models import CompassModels, merged_models  # noqa: E402


def test_compass_wins_phase_by_phase_and_the_repo_file_fills_the_rest():
    repo_file = {"implementer": ["claude-opus-5"], "reviewer": ["claude-sonnet-5"]}
    got = merged_models(repo_file, {"implementer": ["claude-opus-5-5", "claude-sonnet-5-5"], "qa": [], "bad": [3]})
    assert got == {"implementer": ["claude-opus-5-5", "claude-sonnet-5-5"], "reviewer": ["claude-sonnet-5"]}
    assert resolve_model("implementer", got, probe_allowing("claude-sonnet-5-5")).model == "claude-sonnet-5-5"


def _compass(handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)
    client = httpx.Client(transport=httpx.MockTransport(wrapped))
    return seen, client


def test_compass_models_are_read_with_the_dispatch_token_and_cached():
    seen, client = _compass(lambda r: httpx.Response(200, json={"models": {"implementer": ["claude-opus-5-5"]}}))
    pull = CompassModels("tok", lambda o, r: "https://compass.test/", client=client)
    assert pull("genai", "beacon-api") == {"implementer": ["claude-opus-5-5"]}
    assert pull("genai", "beacon-api") == {"implementer": ["claude-opus-5-5"]}
    assert len(seen) == 1
    assert str(seen[0].url) == "https://compass.test/api/orchestrator/models?repo=genai%2Fbeacon-api"
    assert seen[0].headers["authorization"] == "Bearer tok"


def test_a_compass_that_is_unknown_old_or_down_sets_nothing():
    _, old = _compass(lambda r: httpx.Response(404, json={"error": "Not Found"}))
    assert CompassModels("tok", lambda o, r: "https://compass.test", client=old)("o", "r") == {}

    def down(r):
        raise httpx.ConnectError("refused")
    _, broken = _compass(down)
    assert CompassModels("tok", lambda o, r: "https://compass.test", client=broken)("o", "r") == {}
    assert CompassModels("tok", lambda o, r: None)("o", "r") == {}
    assert CompassModels("", lambda o, r: "https://compass.test")("o", "r") == {}


# --- why a model was skipped -------------------------------------------------

import subprocess  # noqa: E402

from factory_orchestrator.models import default_probe, probe_reason  # noqa: E402


def test_a_skipped_model_carries_the_probes_reason():
    def probe(m):
        return m == "claude-sonnet-5-5"
    probe.reasons = {"claude-opus-5-5": "Claude refused it (exit 1): model not available on your plan"}
    got = resolve_model("release", {"release": ["claude-opus-5-5", "claude-sonnet-5-5"]}, probe)
    assert got.model == "claude-sonnet-5-5"
    assert got.reasons == {"claude-opus-5-5": "Claude refused it (exit 1): model not available on your plan"}
    # A probe that keeps no reasons still resolves, and says so.
    assert resolve_model("release", {"release": ["a", "b"]}, probe_allowing("b")).reasons == {"a": "no reason recorded"}


def test_the_reason_is_one_line_with_secrets_masked():
    assert probe_reason("warming up\nAPI Error: 404 model claude-opus-5-5 not found\n\n") == \
        "API Error: 404 model claude-opus-5-5 not found"
    assert "sk-ant" not in probe_reason("bad token sk-ant-oat01-abcDEF_123")
    assert probe_reason("") == "no output"


def test_the_default_probe_records_why_it_failed(monkeypatch):
    cfg = type("Cfg", (), {"agent_credential_env": lambda self: {"CLAUDE_CODE_OAUTH_TOKEN": "t"}})()
    outcomes = {
        "refused": subprocess.CompletedProcess([], 1, stdout="API Error: model not available\n", stderr=""),
        "ok": subprocess.CompletedProcess([], 0, stdout="OK", stderr=""),
    }

    def fake_run(argv, **_):
        model = argv[argv.index("--model") + 1]
        if model == "slow":
            raise subprocess.TimeoutExpired(argv, 120)
        return outcomes[model]
    monkeypatch.setattr(subprocess, "run", fake_run)
    probe = default_probe(cfg)
    assert probe("refused") is False and probe("slow") is False and probe("ok") is True
    assert probe.reasons["refused"] == "Claude refused it (exit 1): API Error: model not available"
    assert "120 seconds" in probe.reasons["slow"]
    assert "ok" not in probe.reasons

    none = default_probe(type("Cfg", (), {"agent_credential_env": lambda self: {}})())
    assert none("x") is False and "no Claude credential" in none.reasons["x"]
