"""The eligibility check: whether a request for an item is within policy.

This is where every policy decision is made. The model never compares an age
with a refresh period or a count with a limit; it receives the verdict and the
reason written here, and relays them.

The module is pure: no files, no lookups, no clock. Whoever calls it has
already found the employee and the policy and passes them in, together with
the date, so a test can build every input from a literal.
"""

from dataclasses import dataclass
from datetime import date

# The three answers a verdict can give. Named once here so a typo in one rule
# cannot quietly invent a fourth.
APPROVED = "approved"
DENIED = "denied"
NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class Verdict:
    """The answer to one question about a request, with the reason for it.

    next_eligible_on is set only when a replacement is denied because the item
    is not old enough yet. Everywhere else it is None, so the model is never
    handed a date it could mistake for a promise.
    """

    verdict: str
    reason: str
    next_eligible_on: date | None

    def to_dict(self) -> dict:
        """Convert to plain types that can be written as JSON."""
        # JSON has no date type, so the date leaves as text such as
        # "2028-08-20". A missing date stays None, which becomes null.
        next_eligible_on = None
        if self.next_eligible_on is not None:
            next_eligible_on = self.next_eligible_on.isoformat()

        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "next_eligible_on": next_eligible_on,
        }


@dataclass(frozen=True)
class EligibilityDecision:
    """The full answer to "may this employee have this item?".

    Both questions are always answered: an additional item, kept alongside what
    they hold, and a replacement for their oldest. A request such as "a
    monitor" often doesn't say which is meant, so the agent picks the verdict
    that matches what the employee asked.

    max_quantity and refresh_years are None when the role is not issued the
    item at all, because there is no limit or cadence to report.
    """

    employee_id: str
    role: str
    item: str
    held: int
    max_quantity: int | None
    refresh_years: int | None
    additional: Verdict
    replacement: Verdict

    def to_dict(self) -> dict:
        """Convert to plain types, ready to be returned by an MCP tool.

        This is the shape the check_request_eligibility tool answers with. Each
        verdict converts itself, the same way each piece of equipment does
        inside Employee.to_dict.
        """
        return {
            "employee_id": self.employee_id,
            "role": self.role,
            "item": self.item,
            "held": self.held,
            "max_quantity": self.max_quantity,
            "refresh_years": self.refresh_years,
            "additional": self.additional.to_dict(),
            "replacement": self.replacement.to_dict(),
        }
