"""Append-only run log the Console polls while a role is in flight.

The ledger still stores the current `guards.phase` (the "Now" field). This
file is the history: one JSON line per notification, plus a transcript that
grows as Claude and `commands.test` print, instead of appearing only when
the process exits.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class LiveRunLog:
    def __init__(self, transcript_path: str | Path):
        self.transcript_path = Path(transcript_path)
        self.events_path = self.transcript_path.with_suffix(".events.jsonl")
        self._lock = threading.Lock()
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        self.transcript_path.write_text("", encoding="utf-8")
        self.events_path.write_text("", encoding="utf-8")

    def event(self, kind: str, message: str) -> dict[str, str]:
        rec = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "kind": kind,
            "message": message,
        }
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with self._lock:
            with self.events_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
        return rec

    def write(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            with self.transcript_path.open("a", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()

    def replace_transcript(self, text: str) -> None:
        with self._lock:
            self.transcript_path.write_text(text or "", encoding="utf-8")


def read_events(transcript_path: str | None, *, limit: int = 500) -> list[dict[str, Any]]:
    if not transcript_path:
        return []
    path = Path(transcript_path).with_suffix(".events.jsonl")
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("message"), str):
            continue
        rows.append({
            "ts": rec["ts"] if isinstance(rec.get("ts"), str) else "",
            "kind": rec["kind"] if isinstance(rec.get("kind"), str) else "phase",
            "message": rec["message"],
        })
    return rows
