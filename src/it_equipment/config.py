"""Application settings: the values that change how the program runs.

Settings are knobs, such as which port to listen on and which files to read
and write. They are not the information the program reasons about: the
employee records and the policy rules are data and live under data/ as JSON.

Settings are built up in three layers, each one overriding the layer before:

    1. the defaults on Settings, so the program runs with no configuration at all
    2. config.toml, the values edited while developing
    3. environment variables, which is how a container changes a setting
       without the image having to be rebuilt

This module is the only place in the package that reads the configuration file
or the environment. Everything else is handed a Settings object, so no other
function depends on what happens to be set outside the program.

There are two deliberate exceptions, both to do with the agent's secrets. The
agent's entry point loads .env into the environment with python-dotenv, and
the anthropic SDK's Foundry client reads its key and resource name from the
environment by itself. That way the key never becomes a field of Settings, an
object that can end up printed.
"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

# The repository root. This file is src/it_equipment/config.py, so the root is
# three levels up: config.py -> it_equipment -> src -> the root.
REPO_ROOT = Path(__file__).parent.parent.parent

DEFAULT_CONFIG_FILE = REPO_ROOT / "config.toml"


@dataclass(frozen=True)
class Settings:
    """Everything the program needs to know in order to run.

    Every field has a default, so Settings() on its own is already usable and
    no configuration file is required.
    """

    host: str = "127.0.0.1"
    port: int = 8000
    path: str = "/mcp"
    employees_file: Path = REPO_ROOT / "data" / "employees.json"
    policies_file: Path = REPO_ROOT / "data" / "policies.json"
    # Where review flags are appended. Its folder is git-ignored, because the
    # flags are written while the server runs rather than authored as data.
    review_queue_file: Path = REPO_ROOT / "review-queue" / "review_queue.jsonl"
    # The model the agent calls. On Microsoft Foundry this is the deployment
    # name, which is the model id unless the deployment was named otherwise.
    model: str = "claude-opus-5"
    # The most calls to the model the agent may make while handling one
    # request. One call is one step.
    max_steps: int = 10

    def mcp_url(self) -> str:
        """Return the address a client connects to.

        Calculated from the other fields rather than stored as a fourth one, so
        the server and the client cannot drift into pointing at different
        addresses.
        """
        return f"http://{self.host}:{self.port}{self.path}"


def resolve_path(path_text: str, base_folder: Path) -> Path:
    """Turn a path from the configuration into one that works from anywhere.

    A relative path is resolved against the folder holding the configuration
    file rather than the current working directory, so "data/employees.json"
    means the same file whether the server is started from the repository root
    or from somewhere else. An absolute path is already unambiguous and is used
    as it stands.
    """
    path = Path(path_text)

    if path.is_absolute():
        return path

    return base_folder / path


def load_settings(config_file: str | Path | None = None) -> Settings:
    """Build the settings by applying the three layers in order.

    The path to the configuration file can be passed in, which is what the
    tests do. Left out, the committed config.toml at the repository root is
    used.
    """
    if config_file is None:
        config_file = DEFAULT_CONFIG_FILE

    config_file = Path(config_file)

    # Layer 1: start from the defaults declared on Settings.
    defaults = Settings()
    host = defaults.host
    port = defaults.port
    path = defaults.path
    employees_file = defaults.employees_file
    policies_file = defaults.policies_file
    review_queue_file = defaults.review_queue_file
    model = defaults.model
    max_steps = defaults.max_steps

    # Layer 2: the configuration file. A missing file is not an error, because
    # the defaults above are already a complete set of settings.
    if config_file.exists():
        with config_file.open("rb") as handle:
            config = tomllib.load(handle)

        # Each key is checked on its own, so a file that sets only the port
        # leaves every other setting at its default.
        if "server" in config:
            server = config["server"]

            if "host" in server:
                host = server["host"]

            if "port" in server:
                port = server["port"]

            if "path" in server:
                path = server["path"]

        if "data" in config:
            data = config["data"]

            if "employees" in data:
                employees_file = resolve_path(data["employees"], config_file.parent)

            if "policies" in data:
                policies_file = resolve_path(data["policies"], config_file.parent)

            if "review_queue" in data:
                review_queue_file = resolve_path(data["review_queue"], config_file.parent)

        if "agent" in config:
            agent = config["agent"]

            if "model" in agent:
                model = agent["model"]

            if "max_steps" in agent:
                max_steps = agent["max_steps"]

    # Layer 3: environment variables, which is how a container overrides a
    # setting without the image being rebuilt.
    if "MCP_HOST" in os.environ:
        host = os.environ["MCP_HOST"]

    if "MCP_PORT" in os.environ:
        # An environment variable is always text, so "9000" has to be turned
        # into the number 9000. A TOML file can write port = 8000 as a number
        # already, which is why only this layer needs the conversion.
        port = int(os.environ["MCP_PORT"])

    if "MCP_PATH" in os.environ:
        path = os.environ["MCP_PATH"]

    if "MCP_EMPLOYEES_FILE" in os.environ:
        employees_file = resolve_path(os.environ["MCP_EMPLOYEES_FILE"], config_file.parent)

    if "MCP_POLICIES_FILE" in os.environ:
        policies_file = resolve_path(os.environ["MCP_POLICIES_FILE"], config_file.parent)

    if "MCP_REVIEW_QUEUE_FILE" in os.environ:
        review_queue_file = resolve_path(os.environ["MCP_REVIEW_QUEUE_FILE"], config_file.parent)

    # No MCP_ prefix on this one: ANTHROPIC_MODEL is the name Anthropic's own
    # tools use, so it sits in .env beside the two Foundry variables the SDK
    # reads for itself.
    if "ANTHROPIC_MODEL" in os.environ:
        model = os.environ["ANTHROPIC_MODEL"]

    if "AGENT_MAX_STEPS" in os.environ:
        # Text from the environment, so it becomes a number the way MCP_PORT does.
        max_steps = int(os.environ["AGENT_MAX_STEPS"])

    return Settings(
        host=host,
        port=port,
        path=path,
        employees_file=employees_file,
        policies_file=policies_file,
        review_queue_file=review_queue_file,
        model=model,
        max_steps=max_steps,
    )
