"""Images people attached to an issue in the Compass, fetched into a run.

The Compass keeps the bytes of a screenshot or mock-up attached from Add
work or Shape; the issue body only links to them, and the links need a
Compass sign-in an agent does not have. So before a role starts, the
orchestrator asks the Compass that dispatches this repo for the issue's
images (and its epic's, for a task, bug or test case), writes them beside
the checkout — never inside it — and names them in the prompt, exactly as
``ask.py`` does for the images a person sends with a question.

The Compass is reached at the ``console_url`` the dispatch carried, with the
dispatch token the orchestrator already holds for re-minting GitHub tokens
(``token_refresh.py``). Nothing here can fail a run: a Compass that is
unreachable, refuses, or has no images for the issue leaves the run exactly
as it was before this module existed — words only.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .router import epic_ref_from_body

log = logging.getLogger("factory-orchestrator.attachments")

LIST_PATH = "/api/orchestrator/attachments"
#: One file, one run, and how many — past these a file is skipped and said so.
MAX_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 30 * 1024 * 1024
MAX_FILES = 12

_SUB_ISSUE_RE = re.compile(r"^(?:task|bug|test)\((\d+)\)", re.IGNORECASE)
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass
class Attachment:
    path: Path
    name: str
    repo: str
    issue: int
    source: str


@dataclass
class Fetched:
    files: list[Attachment] = field(default_factory=list)
    skipped: int = 0


def attachment_targets(port: Any, repo: str, issue: int) -> list[tuple[str, int]]:
    """The issues whose images a run on `issue` reads: itself, and — for a
    `task(N)`, `bug(N)` or `test(N)` sub-issue — its epic, in the same repo
    or in the one the body's `Part of owner/repo#N` marker names. The title
    gives the number and the marker only the repo, as the router reads them.
    """
    targets = [(repo, issue)]
    try:
        data = port.get_issue(issue) or {}
    except Exception:  # noqa: BLE001 - the issue's own images still count
        return targets
    m = _SUB_ISSUE_RE.match(data.get("title") or "")
    if m:
        epic_repo, _ = epic_ref_from_body(data.get("body"))
        targets.append((epic_repo or repo, int(m.group(1))))
    return targets


class ConsoleAttachments:
    """Fetch an issue's images from the Compass into a folder."""

    def __init__(self, dispatch_token: str, *, client: httpx.Client | None = None,
                 timeout: float = 20.0, max_bytes: int = MAX_BYTES,
                 max_total: int = MAX_TOTAL_BYTES, max_files: int = MAX_FILES):
        self.dispatch_token = dispatch_token
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_total = max_total
        self.max_files = max_files
        self._client = client

    def fetch(self, console_url: str | None, targets: list[tuple[str, int]], dest: Path) -> Fetched:
        """Download the images of every `(owner/repo, issue)` in `targets`
        into `dest/<issue>/<name>`. Partial on any error; never raises."""
        out = Fetched()
        if not console_url or not self.dispatch_token or not targets:
            return out
        base = console_url.rstrip("/")
        headers = {"Authorization": f"Bearer {self.dispatch_token}"}
        client = self._client or httpx.Client(timeout=self.timeout)
        total = 0
        try:
            for repo, issue in targets:
                try:
                    r = client.get(f"{base}{LIST_PATH}", params={"repo": repo, "issue": issue}, headers=headers)
                except httpx.HTTPError as e:
                    log.warning("attachments: could not reach the Compass at %s for %s#%s: %s", base, repo, issue, e)
                    continue
                if r.status_code >= 400:
                    log.warning("attachments: Compass %s returned %s for %s#%s", LIST_PATH, r.status_code, repo, issue)
                    continue
                try:
                    items = list((r.json() or {}).get("attachments") or [])
                except ValueError:
                    log.warning("attachments: Compass %s returned no JSON for %s#%s", LIST_PATH, repo, issue)
                    continue
                folder = dest / str(issue)
                for item in items:
                    size = int(item.get("size") or 0)
                    if len(out.files) >= self.max_files or size > self.max_bytes or total + size > self.max_total:
                        out.skipped += 1
                        continue
                    url = str(item.get("url") or "")
                    if not url:
                        out.skipped += 1
                        continue
                    try:
                        g = client.get(url if url.startswith("http") else f"{base}{url}", headers=headers)
                    except httpx.HTTPError as e:
                        log.warning("attachments: could not fetch %s: %s", url, e)
                        out.skipped += 1
                        continue
                    if g.status_code >= 400 or not g.content:
                        out.skipped += 1
                        continue
                    folder.mkdir(parents=True, exist_ok=True)
                    path = _free_path(folder, _safe_name(str(item.get("name") or "image"), str(item.get("mime") or "")))
                    path.write_bytes(g.content)
                    total += len(g.content)
                    out.files.append(Attachment(path=path, name=path.name, repo=repo, issue=issue,
                                                source=str(item.get("source") or "")))
        finally:
            if self._client is None:
                client.close()
        if out.files or out.skipped:
            log.info("attachments: fetched %d file(s), skipped %d, for %s",
                     len(out.files), out.skipped, ", ".join(f"{r}#{n}" for r, n in targets))
        return out


_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}


def _safe_name(name: str, mime: str) -> str:
    safe = _SAFE_NAME_RE.sub("_", name).strip("._")[:80] or "image"
    if "." not in safe and mime in _EXT:
        safe += _EXT[mime]
    return safe


def _free_path(folder: Path, name: str) -> Path:
    path = folder / name
    stem, dot, ext = name.rpartition(".")
    n = 2
    while path.exists():
        path = folder / (f"{stem}-{n}.{ext}" if dot else f"{name}-{n}")
        n += 1
    return path


def attachments_note(fetched: Fetched, issue: int) -> str:
    """The prompt block naming the fetched files, or "" when there are none."""
    if not fetched.files and not fetched.skipped:
        return ""
    own = [a for a in fetched.files if a.issue == issue]
    epic = [a for a in fetched.files if a.issue != issue]
    parts = []
    if own:
        parts.append(f"{len(own)} image{'s' if len(own) != 1 else ''} to this issue")
    if epic:
        parts.append(f"{len(epic)} to its epic #{epic[0].issue}")
    lines = [f"- {a.path}  ({'this issue' if a.issue == issue else f'epic #{a.issue}'})" for a in fetched.files]
    out = ["===== ATTACHMENTS =====", ""]
    if parts:
        out.append(f"The person attached {' and '.join(parts)}. View each with the Read tool "
                   "before you start; they show what the words leave out.")
        out.extend(lines)
    if fetched.skipped:
        out.append(f"({fetched.skipped} image{'s were' if fetched.skipped != 1 else ' was'} skipped: too large or too many.)")
    out.append("")
    return "\n".join(out) + "\n"
