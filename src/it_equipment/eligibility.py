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

from it_equipment.models import Employee, EquipmentItem, RolePolicy, date_after_whole_years

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


def decide_eligibility(
    employee: Employee,
    policy: RolePolicy,
    catalogue: list[str],
    item: str,
    as_of: date,
) -> EligibilityDecision:
    """Decide whether the employee may have one more of the item, or a replacement.

    The rules are checked in the order agreed in docs/requirements.md, and the
    first that applies decides. Rules 1 to 3 settle both questions at once;
    only when none of them applies are the two questions answered separately.

    The item must already be lower-cased and trimmed. That is done once, where
    the request comes in, so this function compares names exactly.
    """
    held_items = items_named(employee, item)
    held = len(held_items)

    # Rule 1: no role's policy mentions the item. It may be a real request the
    # rules don't cover, or the wrong word for a covered item, so a person
    # looks at it. Listing the covered items lets the agent retry with the
    # right word.
    if item not in catalogue:
        covered = ", ".join(catalogue)
        reason = f"No policy covers '{item}'. The items covered are: {covered}."
        verdict = Verdict(verdict=NEEDS_REVIEW, reason=reason, next_eligible_on=None)
        return EligibilityDecision(
            employee_id=employee.employee_id,
            role=employee.role,
            item=item,
            held=held,
            max_quantity=None,
            refresh_years=None,
            additional=verdict,
            replacement=verdict,
        )

    # Rule 2: the item is in the catalogue, but not for this role.
    if not policy.issues(item):
        reason = f"Employees in the {employee.role} role are not issued a {item}."
        verdict = Verdict(verdict=DENIED, reason=reason, next_eligible_on=None)
        return EligibilityDecision(
            employee_id=employee.employee_id,
            role=employee.role,
            item=item,
            held=held,
            max_quantity=None,
            refresh_years=None,
            additional=verdict,
            replacement=verdict,
        )

    allowance = policy.allowance_for(item)

    # Rule 3: the records show more than the role may hold. Either the records
    # or the policy is wrong, and neither question can be answered safely
    # until a person has found out which.
    if held > allowance.max_quantity:
        reason = (
            f"{employee.employee_id}'s records show {count_of(held, item)}, but employees in "
            f"the {employee.role} role may hold {allowance.max_quantity}. The records "
            f"disagree with the policy."
        )
        verdict = Verdict(verdict=NEEDS_REVIEW, reason=reason, next_eligible_on=None)
        return EligibilityDecision(
            employee_id=employee.employee_id,
            role=employee.role,
            item=item,
            held=held,
            max_quantity=allowance.max_quantity,
            refresh_years=allowance.refresh_years,
            additional=verdict,
            replacement=verdict,
        )

    # Rules 4 and 5: each question now gets its own answer.
    return EligibilityDecision(
        employee_id=employee.employee_id,
        role=employee.role,
        item=item,
        held=held,
        max_quantity=allowance.max_quantity,
        refresh_years=allowance.refresh_years,
        additional=decide_additional(employee, item, held, allowance.max_quantity),
        replacement=decide_replacement(employee, item, held_items, allowance.refresh_years, as_of),
    )


def decide_additional(employee: Employee, item: str, held: int, max_quantity: int) -> Verdict:
    """Rule 4: may the employee have one more, kept alongside what they hold?"""
    limit = (
        f"Employees in the {employee.role} role may hold {count_of(max_quantity, item)} "
        f"and {employee.employee_id} holds {held}."
    )

    if held < max_quantity:
        return Verdict(
            verdict=APPROVED,
            reason=f"{limit} One more can be issued.",
            next_eligible_on=None,
        )

    # Said in words so the model has no gap to fill: the answer changes only
    # if one is handed back, not on any date.
    no_date = (
        f"Another {item} is not issued while {count_of(held, item)} {is_or_are(held)} held, "
        f"so there is no date on which this changes."
    )
    return Verdict(verdict=DENIED, reason=f"{limit} {no_date}", next_eligible_on=None)


def decide_replacement(
    employee: Employee,
    item: str,
    held_items: list[EquipmentItem],
    refresh_years: int,
    as_of: date,
) -> Verdict:
    """Rule 5: may the employee have a new one in place of their oldest?"""
    if len(held_items) == 0:
        return Verdict(
            verdict=DENIED,
            reason=f"{employee.employee_id} holds no {item}, so there is nothing to replace.",
            next_eligible_on=None,
        )

    # The oldest is the one that goes back, so it is the one whose age counts.
    oldest = held_items[0]
    for held_item in held_items:
        if held_item.issued_on < oldest.issued_on:
            oldest = held_item

    age = oldest.age_years(as_of)

    # "oldest" only means something when there is more than one.
    which = f"{employee.employee_id}'s {item}"
    if len(held_items) > 1:
        which = f"{employee.employee_id}'s oldest {item}"

    reason = (
        f"{which} is {count_of(age, 'year')} old; {item}s in the {employee.role} role "
        f"are replaced after {count_of(refresh_years, 'year')}."
    )

    if age >= refresh_years:
        return Verdict(verdict=APPROVED, reason=reason, next_eligible_on=None)

    # Worked out here, so the model relays a date rather than calculating one.
    due = date_after_whole_years(oldest.issued_on, refresh_years)
    return Verdict(verdict=DENIED, reason=reason, next_eligible_on=due)


def items_named(employee: Employee, item: str) -> list[EquipmentItem]:
    """Return the pieces of equipment on file with this name."""
    matching = []
    for equipment in employee.equipment:
        if equipment.name == item:
            matching.append(equipment)

    return matching


def count_of(number: int, noun: str) -> str:
    """Write a count with its noun, such as "1 laptop" or "2 monitors"."""
    # Every item in the catalogue, and "year", takes a plain "s" in the plural.
    if number == 1:
        return f"{number} {noun}"

    return f"{number} {noun}s"


def is_or_are(number: int) -> str:
    """Return the verb that agrees with a count: "1 is", "2 are"."""
    if number == 1:
        return "is"

    return "are"
