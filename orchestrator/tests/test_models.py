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
    assert probe.calls == DEFAULT_CHAIN


def test_string_chain_and_junk_config():
    assert chain_for("x", {"x": "solo"}) == ["solo"]
    assert chain_for("x", {"x": []}) == DEFAULT_CHAIN
    assert chain_for("x", {"x": [1, 2]}) == DEFAULT_CHAIN


def test_exhausted_chain_raises():
    with pytest.raises(ModelResolutionError, match="factory-models.json"):
        resolve_model("intake", {"intake": ["a", "b"]}, probe_allowing())
