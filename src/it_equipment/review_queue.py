"""The review queue: where requests that need a person are recorded.

Each flag is appended to a file as one line of JSON, a format called JSON
Lines. It is the usual lightweight stand-in for a ticket system: it survives a
restart, any text editor can read it, and adding a flag never rewrites the
ones before it.

ReviewQueue.add is the only code in the package that writes a file.

Nothing here reads the clock or makes an id. A flag arrives complete, with its
id and time already set by the MCP tool, so a test can pass fixed values.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class ReviewFlag:
    """One request sent to a person to decide, and why it was sent."""

    flag_id: str
    employee_id: str
    request: str
    reason: str
    flagged_at: datetime

    def to_dict(self) -> dict:
        """Convert to plain types that can be written as JSON.

        This is both the line written to the queue file and the flag the
        flag_for_human_review tool answers with.
        """
        return {
            "flag_id": self.flag_id,
            "employee_id": self.employee_id,
            "request": self.request,
            "reason": self.reason,
            # JSON has no time type, so the time leaves as ISO 8601 text such
            # as "2026-11-26T14:03:12+00:00". Seconds are as precise as a
            # reviewer needs, and the "+00:00" says the time is in UTC.
            "flagged_at": self.flagged_at.isoformat(timespec="seconds"),
        }


class ReviewQueue:
    """The file that review flags are appended to, one line of JSON each.

    Creating a queue only stores the path; nothing touches the disk until a
    flag is added. Building a server, or a test, therefore creates no files.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def add(self, flag: ReviewFlag) -> None:
        """Append one flag to the end of the file as a single line of JSON.

        The folder is created if it does not exist yet, so the first flag on a
        fresh checkout, or in a new container volume, does not fail.
        """
        # Done on every add rather than once at start-up, so a folder deleted
        # while the server runs is simply made again.
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # json.dumps writes a line break inside the text as the two characters
        # \n, so a request typed over several lines is still one line here.
        line = json.dumps(flag.to_dict()) + "\n"

        # The SDK runs tools on worker threads, so two flags can arrive at the
        # same moment. Append mode puts every write at the end of the file, and
        # on a local disk the operating system does each write in one piece, so
        # they land as two whole lines rather than one mixed one. That stops
        # holding on a network drive or with several servers sharing the file;
        # those, or needing to change a flag once written, are the point to
        # move to a database or a ticket system.
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line)
