"""The agent: takes an employee's equipment request and investigates it with the MCP server's tools.

It connects to the server as an MCP client and hands the request to the model,
which decides which tool to call. Each module does one job: mcp_bridge.py is
the only one that imports mcp, and __main__.py is the only one that loads .env.
"""
