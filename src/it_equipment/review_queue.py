"""The review queue: where requests that need a person are recorded.

Nothing here reads the clock or makes an id. A flag arrives complete, with its
id and time already set by the MCP tool, so a test can pass fixed values.
"""

from dataclasses import dataclass
from datetime import datetime


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
