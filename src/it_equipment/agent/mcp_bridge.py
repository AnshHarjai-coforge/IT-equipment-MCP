"""The agent's side of MCP: the only agent module that imports mcp.

It does two conversions, one in each direction:

    - An MCP tool becomes a Claude tool definition, with one extra required
      argument, thought, so that every Action the model asks for comes with
      its reason. The server's own tools are not changed: the thought is
      removed again before the server is called.
    - A tool result becomes the observation text the model reads and the
      trace prints.

Keeping these here means the rest of the agent never handles an MCP object's
insides, and each conversion is tested on its own, from literal mcp.types
objects, with no server and no model.
"""

import copy
import inspect
import json
from typing import Any

from mcp import Client
from mcp.types import CallToolResult, Tool

# The name of the argument the agent adds to every tool. Written once, here,
# so the code that adds it and the code that removes it cannot disagree.
THOUGHT_FIELD = "thought"

THOUGHT_DESCRIPTION = (
    "Why you are calling this tool now: what you know so far and what you need it "
    "to tell you, in one or two sentences."
)


def connect_to_server(url: str) -> Client:
    """Return an MCP client for the server at this address.

    Nothing connects yet: the client connects when it is opened with
    "async with". It is made here so that no other agent module needs an mcp
    import.
    """
    return Client(url)


def claude_tool_from_mcp_tool(tool: Tool) -> dict[str, Any]:
    """Return the Claude tool definition for one MCP tool, with a thought argument added.

    The definition keeps only what a Claude tool has room for: the name, the
    description and the input schema. The MCP tool's annotations and output
    schema have no place in it and are left out.

    Raises ValueError if the tool already has an argument named thought, since
    the agent could not tell the model's reason apart from a real argument.
    """
    # A full copy, so that adding the thought below can never change the MCP
    # tool's own schema.
    schema = copy.deepcopy(tool.input_schema)

    existing_properties = {}
    if "properties" in schema:
        existing_properties = schema["properties"]

    if THOUGHT_FIELD in existing_properties:
        raise ValueError(
            f"The tool {tool.name} already has an argument named '{THOUGHT_FIELD}', "
            "which the agent adds to every tool itself."
        )

    # The thought goes first. The model tends to fill in arguments in the order
    # the schema lists them, so it writes down its reason before it chooses the
    # rest.
    properties = {THOUGHT_FIELD: {"type": "string", "description": THOUGHT_DESCRIPTION}}
    for name in existing_properties:
        properties[name] = existing_properties[name]
    schema["properties"] = properties

    # Required, so every Action comes with its Thought.
    required = [THOUGHT_FIELD]
    if "required" in schema:
        for name in schema["required"]:
            required.append(name)
    schema["required"] = required

    claude_tool = {"name": tool.name}

    # The SDK hands over the docstring exactly as written in the source, so
    # every line after the first starts with eight spaces. cleandoc removes
    # that indentation, which gives the model the docstring as it reads in the
    # code. A tool with no description simply has none in Claude either.
    if tool.description is not None:
        claude_tool["description"] = inspect.cleandoc(tool.description)

    claude_tool["input_schema"] = schema
    return claude_tool


async def claude_tools_from_server(mcp_client: Client) -> list[dict[str, Any]]:
    """Return every tool the server offers, as Claude tool definitions.

    The server lists all of its tools in one reply, so one request is enough.
    """
    listed = await mcp_client.list_tools()

    claude_tools = []
    for tool in listed.tools:
        claude_tools.append(claude_tool_from_mcp_tool(tool))

    return claude_tools


def thought_from_arguments(arguments: dict[str, Any]) -> str:
    """Return the thought the model gave with a tool call, or "" if it gave none."""
    if THOUGHT_FIELD not in arguments:
        return ""

    return arguments[THOUGHT_FIELD]


def arguments_without_thought(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a new dictionary of the tool call's arguments, without the thought.

    This is what the server is called with, since its tools have no thought
    argument. A new dictionary is made, rather than the thought being deleted
    from the model's own, because the model's tool call is sent back to it
    with the next request and must still be exactly what it wrote.
    """
    without_thought = {}
    for name in arguments:
        if name != THOUGHT_FIELD:
            without_thought[name] = arguments[name]

    return without_thought


def flag_id_from_result(result: CallToolResult) -> str:
    """Return the flag_id from a successful flag_for_human_review result.

    Only for a result that is not an error: an error carries no dictionary,
    so check is_error first.
    """
    return result.structured_content["flag_id"]


def observation_text(result: CallToolResult) -> str:
    """Return a tool result as the text the model reads and the trace prints.

    A success carries the tool's dictionary, which becomes indented JSON. An
    error carries no dictionary, only a message such as
    'Error executing tool get_employee_info: "No employee with id 'E999'"',
    so the message itself is returned.
    """
    if result.structured_content is not None:
        # Indented, because the same text is printed in the trace and one long
        # line is hard to read. ensure_ascii=False keeps an employee's own
        # words as they wrote them: a curly apostrophe stays one, rather than
        # becoming the escape code ’.
        return json.dumps(result.structured_content, indent=2, ensure_ascii=False)

    texts = []
    for block in result.content:
        # A result can also carry images or links, and only text blocks have
        # text. Our server sends only text.
        if block.type == "text":
            texts.append(block.text)

    return "\n".join(texts)
