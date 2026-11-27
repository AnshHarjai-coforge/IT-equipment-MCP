"""Unit tests for the system prompt and the reviewer prompt.

The wording itself is reviewed by reading it. What these tests catch is the
prompt drifting away from the code it describes: a renamed tag or a renamed
tool would leave the model following instructions that no longer match.
"""

from it_equipment.agent.prompts import REVIEWER_PROMPT, SYSTEM_PROMPT
from it_equipment.agent.request import REQUEST_TAG


def test_the_prompt_names_the_tag_the_request_is_wrapped_in():
    assert f"<{REQUEST_TAG}>" in SYSTEM_PROMPT


def test_the_prompt_names_the_tools_it_tells_the_model_to_call():
    for tool_name in ["get_employee_info", "check_request_eligibility", "flag_for_human_review"]:
        assert tool_name in SYSTEM_PROMPT


def test_the_prompt_names_both_verdicts_by_their_field_names():
    """The same words check_request_eligibility returns, so the model can match them."""
    assert '"additional"' in SYSTEM_PROMPT
    assert '"replacement"' in SYSTEM_PROMPT


def test_the_reviewer_prompt_names_the_tag_the_request_is_wrapped_in():
    assert f"<{REQUEST_TAG}>" in REVIEWER_PROMPT


def test_the_reviewer_prompt_names_the_tool_whose_verdicts_decide():
    assert "check_request_eligibility" in REVIEWER_PROMPT


def test_the_reviewer_prompt_names_both_verdicts_by_their_field_names():
    assert '"additional"' in REVIEWER_PROMPT
    assert '"replacement"' in REVIEWER_PROMPT
