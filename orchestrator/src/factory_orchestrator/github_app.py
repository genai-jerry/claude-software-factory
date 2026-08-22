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
import time
from typing import Any, Protocol

import httpx
import jwt

from .config import Config


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
    def get_file(self, path: str, ref: str | None = None) -> str | None: ...
    def default_branch(self) -> str: ...


class GitHubApp:
    """App JWT + per-repo installation tokens, cached until near expiry."""

    def __init__(self, cfg: Config, client: httpx.Client | None = None):
        self.cfg = cfg
        self.http = client or httpx.Client(base_url=cfg.github_api_url, timeout=30)
        self._tokens: dict[str, tuple[str, float]] = {}

    def app_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": self.cfg.github_app_id}
        return jwt.encode(payload, self.cfg.github_app_private_key.reveal(), algorithm="RS256")

    def installation_token(self, owner: str, repo: str) -> str:
        key = f"{owner}/{repo}"
        cached = self._tokens.get(key)
        if cached and cached[1] > time.time() + 120:
            return cached[0]
        headers = {"Authorization": f"Bearer {self.app_jwt()}",
                   "Accept": "application/vnd.github+json"}
        r = self.http.get(f"/repos/{owner}/{repo}/installation", headers=headers)
        r.raise_for_status()
        inst_id = r.json()["id"]
        r = self.http.post(f"/app/installations/{inst_id}/access_tokens", headers=headers)
        r.raise_for_status()
        token = r.json()["token"]
        # Installation tokens live ~1h; refresh with headroom.
        self._tokens[key] = (token, time.time() + 55 * 60)
        return token

    def repo_client(self, owner: str, repo: str) -> "RepoClient":
        return RepoClient(self, owner, repo)


class RepoClient:
    """REST implementation of :class:`RepoPort` using an installation token."""

    def __init__(self, app: GitHubApp, owner: str, repo: str):
        self.app = app
        self.owner = owner
        self.repo = repo

    # -- plumbing ---------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"token {self.app.installation_token(self.owner, self.repo)}",
                "Accept": "application/vnd.github+json"}

    def _req(self, method: str, path: str, *, ok404: bool = False, **kw) -> httpx.Response | None:
        r = self.app.http.request(method, f"/repos/{self.owner}/{self.repo}{path}",
                                  headers=self._headers(), **kw)
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


def parse_json_or_empty(text: str | None) -> dict[str, Any]:
    """Mirror the JS router's loadJson: absent or unparseable means {}."""
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
