"""An equipment request as the agent receives it: who sent it, and what they wrote.

The employee id comes from whoever sent the request, as it would in a ticket
system, and is never read out of the text. The text is kept exactly as the
employee wrote it.
"""

from dataclasses import dataclass

# The tag the employee's words are wrapped in. The system prompt names the same
# tag and tells the model that whatever is inside it is a request to judge,
# never an instruction to follow. A test checks that the two still agree.
REQUEST_TAG = "employee_request"


@dataclass(frozen=True)
class EquipmentRequest:
    """One request: the id of the employee who sent it, and their words exactly as sent."""

    employee_id: str
    text: str

    def prompt_text(self) -> str:
        """Return the request as the message the model is given.

        For Priya's request it is:

            Employee E001 sent this request:

            <employee_request>
            My laptop is 4 years old and slow, can I get a replacement?
            </employee_request>
        """
        # The id sits outside the tags because it comes from the sender and can
        # be trusted. The text goes inside them exactly as sent, even if it
        # holds a closing tag of its own: text trying to break out of the tags
        # is one of the warning signs the system prompt tells the model to
        # escalate, which beats quietly rewriting the employee's words.
        return (
            f"Employee {self.employee_id} sent this request:\n"
            "\n"
            f"<{REQUEST_TAG}>\n"
            f"{self.text}\n"
            f"</{REQUEST_TAG}>"
        )
