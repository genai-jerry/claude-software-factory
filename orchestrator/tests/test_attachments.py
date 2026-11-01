"""The Compass's images for an issue, fetched into a run (attachments.py).

The client lists an issue's images, downloads them under the issue's
number, skips what is too large or too many and says so, and comes back
with what it has on any error — a run never fails for want of a picture.
"""
import httpx

from factory_orchestrator.attachments import (
    ConsoleAttachments,
    Fetched,
    attachment_targets,
    attachments_note,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8
CONSOLE = "https://console.test"


def console(handler):
    return ConsoleAttachments("tok", client=httpx.Client(transport=httpx.MockTransport(handler)))


def listing(items):
    return httpx.Response(200, json={"attachments": items})


def item(id_, name, size=len(PNG), source="work", mime="image/png"):
    return {"id": id_, "source": source, "name": name, "mime": mime, "size": size,
            "url": f"/api/orchestrator/attachments/{source}/{id_}"}


def test_downloads_each_issues_images_under_its_number(tmp_path):
    seen = []

    def handler(r):
        seen.append((r.url.path, dict(r.url.params), r.headers.get("authorization")))
        if r.url.path == "/api/orchestrator/attachments":
            if r.url.params["issue"] == "115":
                return listing([item("a", "shot.png"), item("b", "mock.png", source="shape", mime="image/webp")])
            return listing([item("c", "epic.png")])
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    got = console(handler).fetch(CONSOLE, [("o/r", 115), ("o/r", 35)], tmp_path / "att")
    assert [(a.issue, a.name, a.source) for a in got.files] == [(115, "shot.png", "work"), (115, "mock.png", "shape"), (35, "epic.png", "work")]
    assert (tmp_path / "att" / "115" / "shot.png").read_bytes() == PNG
    assert (tmp_path / "att" / "35" / "epic.png").exists()
    assert got.skipped == 0
    # Every call carried the dispatch token, and the listing named the repo.
    assert all(auth == "Bearer tok" for _, _, auth in seen)
    assert seen[0][1] == {"repo": "o/r", "issue": "115"}


def test_skips_what_is_too_large_or_too_many_and_dedupes_names(tmp_path):
    def handler(r):
        if r.url.path == "/api/orchestrator/attachments":
            return listing([item("a", "shot.png"), item("b", "shot.png"), item("c", "huge.png", size=99_000_000), item("d", "one more.png")])
        return httpx.Response(200, content=PNG)

    client = ConsoleAttachments("tok", client=httpx.Client(transport=httpx.MockTransport(handler)), max_files=3)
    got = client.fetch(CONSOLE, [("o/r", 7)], tmp_path / "att")
    assert [a.name for a in got.files] == ["shot.png", "shot-2.png", "one_more.png"]
    assert got.skipped == 1  # the huge one; the fourth fit within max_files after it was skipped


def test_partial_on_an_error_and_nothing_without_a_console(tmp_path):
    def handler(r):
        if r.url.path == "/api/orchestrator/attachments":
            if r.url.params["issue"] == "1":
                return httpx.Response(500, text="boom")
            return listing([item("a", "ok.png"), item("b", "gone.png")])
        if r.url.path.endswith("/b"):
            return httpx.Response(404)
        return httpx.Response(200, content=PNG)

    got = console(handler).fetch(CONSOLE, [("o/r", 1), ("o/r", 2)], tmp_path / "att")
    assert [a.name for a in got.files] == ["ok.png"]
    assert got.skipped == 1
    assert console(handler).fetch(None, [("o/r", 2)], tmp_path / "x").files == []
    assert ConsoleAttachments("", client=httpx.Client(transport=httpx.MockTransport(handler))).fetch(CONSOLE, [("o/r", 2)], tmp_path / "y").files == []
    assert not (tmp_path / "x").exists()


def test_unreachable_console_yields_nothing(tmp_path):
    def handler(r):
        raise httpx.ConnectError("down")

    got = console(handler).fetch(CONSOLE, [("o/r", 2)], tmp_path / "att")
    assert got.files == [] and got.skipped == 0


class Port:
    def __init__(self, issues):
        self.issues = issues

    def get_issue(self, n):
        return self.issues.get(n)


def test_targets_are_the_issue_and_its_epic():
    port = Port({
        5: {"title": "Add renewals", "body": ""},
        62: {"title": "task(5): compute counts", "body": "Part of #5"},
        70: {"title": "bug(5): wrong total", "body": "Part of o/api#5"},
        80: {"title": "test(5): ST-1 totals", "body": ""},
    })
    assert attachment_targets(port, "o/r", 5) == [("o/r", 5)]
    assert attachment_targets(port, "o/r", 62) == [("o/r", 62), ("o/r", 5)]
    assert attachment_targets(port, "o/r", 70) == [("o/r", 70), ("o/api", 5)]
    assert attachment_targets(port, "o/r", 80) == [("o/r", 80), ("o/r", 5)]
    assert attachment_targets(port, "o/r", 99) == [("o/r", 99)]


def test_note_names_each_file_and_where_it_came_from(tmp_path):
    from factory_orchestrator.attachments import Attachment
    fetched = Fetched(files=[
        Attachment(path=tmp_path / "115" / "shot.png", name="shot.png", repo="o/r", issue=115, source="work"),
        Attachment(path=tmp_path / "35" / "mock.png", name="mock.png", repo="o/r", issue=35, source="shape"),
    ], skipped=1)
    note = attachments_note(fetched, 115)
    assert note.startswith("===== ATTACHMENTS =====")
    assert "1 image to this issue and 1 to its epic #35" in note
    assert f"- {tmp_path / '115' / 'shot.png'}  (this issue)" in note
    assert f"- {tmp_path / '35' / 'mock.png'}  (epic #35)" in note
    assert "1 image was skipped" in note
    assert attachments_note(Fetched(), 115) == ""
