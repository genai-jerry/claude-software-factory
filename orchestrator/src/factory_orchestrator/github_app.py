"""GitHub access: webhook verification, App auth, and the repo port.

The router and graph nodes talk to GitHub through :class:`RepoPort`, a small
protocol mirroring exactly the calls the Actions router makes through
`actions/github-script`. The real implementation (:class:`RepoClient`)
speaks REST with an installation token; the conformance tests substitute an
in-memory fake implementing the same protocol, which is what lets the shared
fixtures drive the Python router without a network.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
import jwt

from .config import Config
from .token_refresh import ConsoleTokenSource, TokenRefreshError

log = logging.getLogger("factory-orchestrator.github")

# A fresh installation token lives ~1h. Never claim more than this for a
# token whose real expiry nobody told us.
TOKEN_LIFETIME = 60 * 60
# What a plain API call needs left on the clock before it bothers re-minting.
MIN_REMAINING_DEFAULT = 120.0
# A token handed to us without an expiry could already be nearly spent, so
# assume little and let the first 401 (or a min_remaining request) correct it.
ASSUMED_TTL = 30 * 60.0


class TokenUnavailableError(RuntimeError):
    """No installation token could be minted, refreshed, or reused."""


def parse_expiry(value: str | None) -> float | None:
    """GitHub's ISO-8601 ``expires_at`` as an epoch, or None if unusable."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Constant-time check of X-Hub-Signature-256."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_header[len("sha256="):], expected)


class RepoPort(Protocol):
    """What routing and guards need from a repository. Numbers are issue numbers."""

    owner: str
    repo: str

    def list_issues(self, *, labels: str | None = None, milestone: int | None = None,
                    state: str = "open") -> list[dict[str, Any]]: ...
    def get_issue(self, number: int) -> dict[str, Any] | None: ...
    def create_issue(self, *, title: str, body: str, labels: list[str],
                     milestone: int | None = None) -> dict[str, Any]: ...
    def add_labels(self, number: int, labels: list[str]) -> None: ...
    def remove_label(self, number: int, label: str) -> None: ...
    def create_comment(self, number: int, body: str) -> None: ...
    def list_comments(self, number: int) -> list[dict[str, Any]]: ...
    def add_assignees(self, number: int, assignees: list[str]) -> None: ...
    def list_open_prs(self, head: str) -> list[dict[str, Any]]: ...
    def merge_pr(self, number: int, method: str = "squash") -> None: ...
    def update_pr_base(self, number: int, base: str) -> None: ...
    def branch_exists(self, name: str) -> bool: ...
    def create_branch(self, name: str, from_branch: str) -> None: ...
    def get_file(self, path: str, ref: str | None = None) -> str | None: ...
    def default_branch(self) -> str: ...


class GitHubApp:
    """App JWT + per-repo installation tokens, held with their real expiry.

    Two things make expiry load-bearing rather than bookkeeping. A role may
    burn the whole ``ROLE_TIMEOUT_SECONDS`` wall clock and *then* have its
    work checked by a guard read, and roles fan out behind ``max_parallel``
    slots so a later one can start close to an hour after the token that
    started the batch was minted. So callers say how much life they need
    (``min_remaining``) instead of trusting a cached string, and a 401 is
    treated as a recoverable staleness signal rather than a fatal error.

    Tokens come from one of two places: an App private key we hold (mint our
    own), or the Console that dispatched the run (:class:`ConsoleTokenSource`).
    The lighthouse-style deployment runs on a placeholder App id and has only
    the second, which is why a stale token there used to be terminal.
    """

    def __init__(self, cfg: Config, client: httpx.Client | None = None,
                 console: ConsoleTokenSource | None = None):
        self.cfg = cfg
        self.http = client or httpx.Client(base_url=cfg.github_api_url, timeout=30)
        self.console = console
        self._tokens: dict[str, tuple[str, float]] = {}

    def app_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": self.cfg.github_app_id}
        return jwt.encode(payload, self.cfg.github_app_private_key.reveal(), algorithm="RS256")

    def can_mint(self) -> bool:
        """Whether we hold a real App key, or only the deployment placeholder."""
        key = self.cfg.github_app_private_key.reveal()
        return ("PRIVATE KEY" in key and "BEGIN" in key
                and self.cfg.github_app_id.strip("0") != "")

    def cache_token(self, owner: str, repo: str, token: str, *,
                    expires_at: float | str | None = None,
                    ttl_seconds: float = ASSUMED_TTL) -> None:
        """Adopt a caller-supplied installation token (Console /dispatch).

        ``expires_at`` is the token's real expiry when the caller knows it.
        Without one we can only assume, and assuming generously is how a
        dead token gets used with confidence — so the fallback is short and
        never longer than a token can live.
        """
        if isinstance(expires_at, str):
            expires_at = parse_expiry(expires_at)
        if expires_at is None:
            expires_at = time.time() + min(ttl_seconds, TOKEN_LIFETIME)
        self._tokens[f"{owner}/{repo}"] = (token, float(expires_at))

    def invalidate(self, owner: str, repo: str) -> None:
        """Drop a cached token — what a 401 tells us about the one we hold."""
        self._tokens.pop(f"{owner}/{repo}", None)

    def token_remaining(self, owner: str, repo: str) -> float:
        """Seconds left on the held token; 0.0 when there is none."""
        cached = self._tokens.get(f"{owner}/{repo}")
        return max(0.0, cached[1] - time.time()) if cached else 0.0

    def installation_token(self, owner: str, repo: str, *,
                           min_remaining: float = MIN_REMAINING_DEFAULT,
                           force_refresh: bool = False) -> str:
        """A token with at least ``min_remaining`` seconds of life left.

        ``min_remaining`` is a request, not a guarantee: nothing can hand back
        more than :data:`TOKEN_LIFETIME`, so a caller that needs longer than an
        hour gets the freshest token available and a warning rather than an
        error. Refusing here would fail runs that the 401 retry can carry.
        """
        key = f"{owner}/{repo}"
        cached = self._tokens.get(key)
        want = min(min_remaining, TOKEN_LIFETIME - 60)
        if not force_refresh and cached and cached[1] > time.time() + want:
            return cached[0]

        errors: list[str] = []
        for source in self._sources():
            try:
                token, expires_at = source(owner, repo)
            except Exception as e:  # noqa: BLE001 - try every source before giving up
                errors.append(f"{type(e).__name__}: {e}")
                continue
            # We just minted this one, so when a source states no expiry the
            # full lifetime is a fact rather than the guess ASSUMED_TTL covers.
            self.cache_token(owner, repo, token, expires_at=expires_at,
                             ttl_seconds=TOKEN_LIFETIME)
            left = self.token_remaining(owner, repo)
            if left < min_remaining:
                log.warning(
                    "the freshest token for %s has %.0fs left but this caller wanted "
                    "%.0fs — long work may need to re-mint mid-run", key, left, min_remaining)
            return token

        # Nothing could mint. A token that is merely too short still beats none.
        if cached and cached[1] > time.time():
            log.warning("reusing a token for %s with %.0fs left; could not re-mint (%s)",
                        key, cached[1] - time.time(), "; ".join(errors) or "no source")
            return cached[0]
        raise TokenUnavailableError(
            f"no usable GitHub installation token for {key}. "
            + (f"Tried: {'; '.join(errors)}. " if errors else "")
            + "Set a real GITHUB_APP_PRIVATE_KEY on the orchestrator, or have the "
              "Console send console_url and installation_id on /dispatch so tokens "
              "can be re-minted at POST /api/orchestrator/github-token.")

    def _sources(self):
        """Token sources in preference order: our own key, then the Console."""
        sources = []
        if self.can_mint():
            sources.append(self._mint_with_jwt)
        if self.console is not None:
            sources.append(self._mint_via_console)
        return sources

    def _mint_with_jwt(self, owner: str, repo: str) -> tuple[str, float | None]:
        headers = {"Authorization": f"Bearer {self.app_jwt()}",
                   "Accept": "application/vnd.github+json"}
        r = self.http.get(f"/repos/{owner}/{repo}/installation", headers=headers)
        r.raise_for_status()
        inst_id = r.json()["id"]
        r = self.http.post(f"/app/installations/{inst_id}/access_tokens", headers=headers)
        r.raise_for_status()
        data = r.json()
        log.info("minted an installation token for %s/%s with the App key", owner, repo)
        return data["token"], parse_expiry(data.get("expires_at"))

    def _mint_via_console(self, owner: str, repo: str) -> tuple[str, float | None]:
        assert self.console is not None
        if not self.console.can_refresh(owner, repo):
            raise TokenRefreshError(f"the Console cannot re-mint for {owner}/{repo}")
        token, expires_at = self.console.mint(owner, repo)
        return token, parse_expiry(expires_at)

    def repo_client(self, owner: str, repo: str) -> RepoClient:
        return RepoClient(self, owner, repo)


class RepoClient:
    """REST implementation of :class:`RepoPort` using an installation token."""

    def __init__(self, app: GitHubApp, owner: str, repo: str):
        self.app = app
        self.owner = owner
        self.repo = repo

    # -- plumbing ---------------------------------------------------------
    def _headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        token = self.app.installation_token(self.owner, self.repo,
                                            force_refresh=force_refresh)
        return {"Authorization": f"token {token}",
                "Accept": "application/vnd.github+json"}

    def _req(self, method: str, path: str, *, ok404: bool = False, **kw) -> httpx.Response | None:
        """One REST call, retried once on 401 with a freshly minted token.

        A 401 here almost always means the installation token aged out during
        a long role rather than that the App lost access: role runs outlive
        the ~1h token, and the guard read that closes a run is the call most
        likely to land after expiry. Retrying once turns what used to end a
        45-minute run into a re-mint nobody notices; if the second call is
        also refused, the error carries that we tried.
        """
        url = f"/repos/{self.owner}/{self.repo}{path}"
        r = self.app.http.request(method, url, headers=self._headers(), **kw)
        if r.status_code == 401:
            log.warning("401 on %s %s - the installation token looks stale, re-minting",
                        method, url)
            self.app.invalidate(self.owner, self.repo)
            try:
                headers = self._headers(force_refresh=True)
            except TokenUnavailableError as e:
                raise TokenUnavailableError(
                    f"GitHub refused the installation token on {method} {url} and it "
                    f"could not be re-minted. {e}") from e
            r = self.app.http.request(method, url, headers=headers, **kw)
            if r.status_code == 401:
                log.error("still 401 on %s %s after re-minting the token", method, url)
        if ok404 and r.status_code == 404:
            return None
        r.raise_for_status()
        return r

    def _paginate(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            r = self._req("GET", path, params={**params, "per_page": 100, "page": page})
            batch = r.json()
            out.extend(batch)
            if len(batch) < 100:
                return out
            page += 1

    # -- RepoPort ---------------------------------------------------------
    def list_issues(self, *, labels=None, milestone=None, state="open"):
        params: dict[str, Any] = {"state": state}
        if labels:
            params["labels"] = labels
        if milestone is not None:
            params["milestone"] = milestone
        return self._paginate("/issues", params)

    def get_issue(self, number: int):
        r = self._req("GET", f"/issues/{number}", ok404=True)
        return None if r is None else r.json()

    def create_issue(self, *, title, body, labels, milestone=None):
        payload: dict[str, Any] = {"title": title, "body": body, "labels": labels}
        if milestone is not None:
            payload["milestone"] = milestone
        return self._req("POST", "/issues", json=payload).json()

    def add_labels(self, number, labels):
        self._req("POST", f"/issues/{number}/labels", json={"labels": labels})

    def remove_label(self, number, label):
        try:
            self._req("DELETE", f"/issues/{number}/labels/{httpx.QueryParams({'l': label})['l']}")
        except httpx.HTTPStatusError as e:  # matches the JS router's .catch(() => {})
            if e.response.status_code != 404:
                raise

    def create_comment(self, number, body):
        self._req("POST", f"/issues/{number}/comments", json={"body": body})

    def list_comments(self, number):
        return self._paginate(f"/issues/{number}/comments", {})

    def add_assignees(self, number, assignees):
        try:
            self._req("POST", f"/issues/{number}/assignees", json={"assignees": assignees})
        except httpx.HTTPStatusError:  # best-effort, like the JS router
            pass

    def list_open_prs(self, head):
        r = self._req("GET", "/pulls", params={"state": "open", "head": head})
        return r.json()

    def merge_pr(self, number, method="squash"):
        self._req("PUT", f"/pulls/{number}/merge", json={"merge_method": method})

    def update_pr_base(self, number, base):
        self._req("PATCH", f"/pulls/{number}", json={"base": base})

    def branch_exists(self, name):
        return self._req("GET", f"/branches/{name}", ok404=True) is not None

    def create_branch(self, name, from_branch):
        r = self._req("GET", f"/branches/{from_branch}")
        sha = r.json()["commit"]["sha"]
        self._req("POST", "/git/refs", json={"ref": f"refs/heads/{name}", "sha": sha})

    def get_file(self, path, ref=None):
        params = {"ref": ref} if ref else {}
        r = self._req("GET", f"/contents/{path}", params=params, ok404=True)
        if r is None:
            return None
        data = r.json()
        if isinstance(data, dict) and data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode()
        return None

    def default_branch(self) -> str:
        r = self._req("GET", "")
        return r.json()["default_branch"]

    def update_issue_state(self, number: int, state: str) -> None:
        self._req("PATCH", f"/issues/{number}", json={"state": state})

    def update_issue_body(self, number: int, body: str) -> None:
        """Rewrite an issue body — used to append a `Blocked by` marker to a
        system test case when its failure files a fix task (FACTORY.md §4b)."""
        self._req("PATCH", f"/issues/{number}", json={"body": body})


def parse_json_or_empty(text: str | None) -> dict[str, Any]:
    """Mirror the JS router's loadJson: absent or unparseable means {}."""
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
