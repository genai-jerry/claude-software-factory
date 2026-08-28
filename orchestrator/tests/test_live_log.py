from factory_orchestrator.live_log import LiveRunLog, read_events


def test_live_run_log_appends_events_and_transcript(tmp_path):
    path = tmp_path / "abc.log"
    live = LiveRunLog(path)
    live.event("phase", "cloning the repo")
    live.write("line one\n")
    live.event("phase", "waiting for tests")
    live.write("test still running\n")
    assert path.read_text() == "line one\ntest still running\n"
    events = read_events(str(path))
    assert [e["message"] for e in events] == ["cloning the repo", "waiting for tests"]
    assert all(e["kind"] == "phase" for e in events)
    live.replace_transcript("final\n")
    assert path.read_text() == "final\n"
    assert read_events(None) == []
    assert read_events(str(tmp_path / "missing.log")) == []
