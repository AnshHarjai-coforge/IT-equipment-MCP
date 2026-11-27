"""Unit tests for turning MCP tools into Claude tools, and tool results into text.

Everything here is built from literal mcp.types objects, shaped like what the
real server sends. No server is started and no model is called, so a failure
points at the conversion itself.
"""

import asyncio

import pytest
from mcp import Client
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations

from it_equipment.agent_tools import (
    THOUGHT_FIELD,
    arguments_without_thought,
    claude_tool_from_mcp_tool,
    claude_tools_from_server,
    connect_to_server,
    observation_text,
    thought_from_arguments,
)

# A docstring exactly as the SDK hands it over: every line after the first
# still carries the eight spaces of indentation it had in the source.
RAW_DOCSTRING = (
    "Get an employee's role.\n"
    "\n"
    "        Fails if no employee has that id.\n"
    "\n"
    "        Args:\n"
    "            employee_id: The employee's id (e.g. E001)\n"
    "        "
)


def employee_info_tool() -> Tool:
    """A tool shaped like the server's get_employee_info, title keys included."""
    return Tool(
        name="get_employee_info",
        description=RAW_DOCSTRING,
        input_schema={
            "type": "object",
            "properties": {"employee_id": {"title": "Employee Id", "type": "string"}},
            "required": ["employee_id"],
            "title": "get_employee_infoArguments",
        },
        output_schema={"type": "object", "additionalProperties": True},
        annotations=ToolAnnotations(readOnlyHint=True),
    )


def tool_with_schema(input_schema: dict) -> Tool:
    return Tool(name="some_tool", description="Does something.", input_schema=input_schema)


class FakeToolLister:
    """Stands in for the MCP client, with only the one method that is used."""

    def __init__(self, tools: list[Tool]) -> None:
        self.tools = tools

    async def list_tools(self) -> ListToolsResult:
        return ListToolsResult(tools=self.tools)


def test_connect_to_server_returns_a_client_for_the_url():
    client = connect_to_server("http://127.0.0.1:8000/mcp")

    assert isinstance(client, Client)
    assert client.server == "http://127.0.0.1:8000/mcp"


def test_the_claude_tool_keeps_the_tool_name():
    claude_tool = claude_tool_from_mcp_tool(employee_info_tool())

    assert claude_tool["name"] == "get_employee_info"


def test_the_description_loses_the_docstring_indentation():
    claude_tool = claude_tool_from_mcp_tool(employee_info_tool())

    assert claude_tool["description"] == (
        "Get an employee's role.\n"
        "\n"
        "Fails if no employee has that id.\n"
        "\n"
        "Args:\n"
        "    employee_id: The employee's id (e.g. E001)"
    )


def test_a_tool_with_no_description_has_none_in_claude():
    tool = Tool(name="some_tool", input_schema={"type": "object", "properties": {}})

    claude_tool = claude_tool_from_mcp_tool(tool)

    assert "description" not in claude_tool


def test_only_the_name_description_and_schema_are_kept():
    """Annotations and the output schema have no place in a Claude tool."""
    claude_tool = claude_tool_from_mcp_tool(employee_info_tool())

    assert list(claude_tool.keys()) == ["name", "description", "input_schema"]


def test_the_thought_is_the_first_argument():
    claude_tool = claude_tool_from_mcp_tool(employee_info_tool())

    properties = claude_tool["input_schema"]["properties"]
    assert list(properties.keys()) == [THOUGHT_FIELD, "employee_id"]


def test_the_thought_is_a_string_with_a_description():
    claude_tool = claude_tool_from_mcp_tool(employee_info_tool())

    thought = claude_tool["input_schema"]["properties"][THOUGHT_FIELD]
    assert thought["type"] == "string"
    assert thought["description"].startswith("Why you are calling this tool now")


def test_the_thought_is_required_before_the_tools_own_arguments():
    claude_tool = claude_tool_from_mcp_tool(employee_info_tool())

    assert claude_tool["input_schema"]["required"] == [THOUGHT_FIELD, "employee_id"]


def test_the_tools_own_argument_is_copied_as_it_is():
    claude_tool = claude_tool_from_mcp_tool(employee_info_tool())

    employee_id = claude_tool["input_schema"]["properties"]["employee_id"]
    assert employee_id == {"title": "Employee Id", "type": "string"}


def test_the_rest_of_the_schema_is_copied_as_it_is():
    claude_tool = claude_tool_from_mcp_tool(employee_info_tool())

    assert claude_tool["input_schema"]["type"] == "object"
    assert claude_tool["input_schema"]["title"] == "get_employee_infoArguments"


def test_the_mcp_tools_own_schema_is_left_unchanged():
    tool = employee_info_tool()

    claude_tool_from_mcp_tool(tool)

    assert list(tool.input_schema["properties"].keys()) == ["employee_id"]
    assert tool.input_schema["required"] == ["employee_id"]


def test_a_tool_with_no_required_arguments_still_requires_the_thought():
    tool = tool_with_schema({"type": "object", "properties": {}})

    claude_tool = claude_tool_from_mcp_tool(tool)

    assert claude_tool["input_schema"]["required"] == [THOUGHT_FIELD]


def test_a_tool_that_already_has_a_thought_raises_value_error():
    tool = tool_with_schema({"type": "object", "properties": {"thought": {"type": "string"}}})

    with pytest.raises(ValueError, match="some_tool"):
        claude_tool_from_mcp_tool(tool)


def test_every_tool_the_server_lists_is_converted_in_order():
    policy_tool = tool_with_schema({"type": "object", "properties": {}})
    lister = FakeToolLister([employee_info_tool(), policy_tool])

    claude_tools = asyncio.run(claude_tools_from_server(lister))

    names = []
    for claude_tool in claude_tools:
        names.append(claude_tool["name"])
    assert names == ["get_employee_info", "some_tool"]


def test_thought_from_arguments_returns_the_thought():
    arguments = {"thought": "I need her role first.", "employee_id": "E001"}

    thought = thought_from_arguments(arguments)

    assert thought == "I need her role first."


def test_a_missing_thought_gives_an_empty_string():
    thought = thought_from_arguments({"employee_id": "E001"})

    assert thought == ""


def test_arguments_without_thought_leaves_out_only_the_thought():
    arguments = {"thought": "Check the laptop.", "employee_id": "E001", "item": "laptop"}

    without = arguments_without_thought(arguments)

    assert without == {"employee_id": "E001", "item": "laptop"}


def test_arguments_without_thought_leaves_the_models_arguments_unchanged():
    """The model's tool call goes back to it later, so it must keep its thought."""
    arguments = {"thought": "I need her role first.", "employee_id": "E001"}

    arguments_without_thought(arguments)

    assert arguments == {"thought": "I need her role first.", "employee_id": "E001"}


def test_a_successful_result_becomes_indented_json():
    result = CallToolResult(
        content=[TextContent(type="text", text="ignored when there is structured content")],
        structured_content={"role": "standard", "tenure_years": 7},
    )

    text = observation_text(result)

    assert text == '{\n  "role": "standard",\n  "tenure_years": 7\n}'


def test_an_error_result_becomes_its_message():
    message = "Error executing tool get_employee_info: \"No employee with id 'E999'\""
    result = CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)

    text = observation_text(result)

    assert text == message


def test_an_employees_own_characters_are_kept_as_written():
    result = CallToolResult(content=[], structured_content={"request": "I’d like a dock"})

    text = observation_text(result)

    assert "I’d like a dock" in text
