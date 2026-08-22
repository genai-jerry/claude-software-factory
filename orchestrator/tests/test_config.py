import pytest

from factory_orchestrator.config import ConfigError, Secret, load_config

BASE = {
    "GITHUB_APP_ID": "1234",
    "GITHUB_APP_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\nxx\n-----END RSA PRIVATE KEY-----",
    "GITHUB_WEBHOOK_SECRET": "whsec",
    "ANTHROPIC_API_KEY": "sk-ant-secret",
}


def test_loads_with_defaults():
    cfg = load_config(BASE)
    assert cfg.engine_name == "langgraph"
    assert cfg.factory_ref == "v1"
    assert cfg.max_parallel_default == 4
    assert cfg.database_url.startswith("sqlite://")


def test_missing_app_id_rejected():
    with pytest.raises(ConfigError, match="GITHUB_APP_ID"):
        load_config({**BASE, "GITHUB_APP_ID": ""})


def test_requires_some_anthropic_credential():
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN"):
        load_config({**BASE, "ANTHROPIC_API_KEY": ""})
    cfg = load_config({**BASE, "ANTHROPIC_API_KEY": "", "CLAUDE_CODE_OAUTH_TOKEN": "oauth"})
    assert cfg.claude_code_oauth_token


def test_invalid_factory_repo_rejected():
    with pytest.raises(ConfigError, match="owner/repo"):
        load_config({**BASE, "FACTORY_REPO": "nope"})


def test_repr_never_leaks_secrets():
    cfg = load_config(BASE)
    shown = repr(cfg)
    assert "sk-ant-secret" not in shown
    assert "whsec" not in shown
    assert "BEGIN RSA" not in shown
    assert "Secret(****)" in shown
    assert repr(cfg.anthropic_api_key) == "Secret(****)"
    assert str(cfg.anthropic_api_key) == "Secret(****)"


def test_secret_reveal_and_bool():
    s = Secret("x")
    assert s.reveal() == "x"
    assert bool(s) and not bool(Secret(""))


def test_private_key_accepts_base64_variant():
    import base64
    pem = BASE["GITHUB_APP_PRIVATE_KEY"]
    env = {**BASE, "GITHUB_APP_PRIVATE_KEY": "",
           "GITHUB_APP_PRIVATE_KEY_B64": base64.b64encode(pem.encode()).decode()}
    assert load_config(env).github_app_private_key.reveal() == pem
    # plain wins when both are set
    both = {**env, "GITHUB_APP_PRIVATE_KEY": "plain-key"}
    assert load_config(both).github_app_private_key.reveal() == "plain-key"


def test_private_key_bad_base64_rejected():
    env = {**BASE, "GITHUB_APP_PRIVATE_KEY": "",
           "GITHUB_APP_PRIVATE_KEY_B64": "!!!not-base64!!!"}
    with pytest.raises(ConfigError, match="B64"):
        load_config(env)
