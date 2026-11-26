"""Unit tests for the settings loader.

The interesting behaviour here is the layering: the defaults, then the
configuration file, then the environment. Each layer is tested on its own, and
then the order between them is tested.

Environment variables are set with monkeypatch.setenv, which undoes itself
after each test. This is the one place monkeypatching is the right tool,
because the environment really is global and a test must not leak into the next
one.
"""

from pathlib import Path

import pytest

from it_equipment.config import (
    DEFAULT_CONFIG_FILE,
    REPO_ROOT,
    Settings,
    load_settings,
    resolve_path,
)

# Every setting that can be overridden from the environment.
ENVIRONMENT_VARIABLES = [
    "MCP_HOST",
    "MCP_PORT",
    "MCP_PATH",
    "MCP_EMPLOYEES_FILE",
    "MCP_POLICIES_FILE",
    "MCP_REVIEW_QUEUE_FILE",
]


@pytest.fixture(autouse=True)
def clear_the_environment(monkeypatch):
    """Start every test in this module from a known environment.

    Without this, a variable left set in the shell that happens to be running
    the tests would quietly change what they assert. A test that wants one of
    these set does so itself.
    """
    for name in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def write_config(folder: Path, text: str) -> Path:
    """Write a configuration file into a temporary folder and return its path."""
    path = folder / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_apply_when_there_is_no_config_file(tmp_path):
    # A path that does not exist, so no file layer can be applied.
    settings = load_settings(tmp_path / "absent.toml")

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.path == "/mcp"


def test_the_config_file_overrides_the_defaults(tmp_path):
    config_file = write_config(
        tmp_path,
        """
        [server]
        host = "0.0.0.0"
        port = 9100
        path = "/tools"
        """,
    )

    settings = load_settings(config_file)

    assert settings.host == "0.0.0.0"
    assert settings.port == 9100
    assert settings.path == "/tools"


def test_a_setting_the_config_file_omits_keeps_its_default(tmp_path):
    """A file that sets only the port must not blank out the host."""
    config_file = write_config(
        tmp_path,
        """
        [server]
        port = 9100
        """,
    )

    settings = load_settings(config_file)

    assert settings.port == 9100
    assert settings.host == "127.0.0.1"


def test_the_environment_beats_the_config_file(tmp_path, monkeypatch):
    config_file = write_config(
        tmp_path,
        """
        [server]
        host = "127.0.0.1"
        port = 8000
        """,
    )
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")

    settings = load_settings(config_file)

    assert settings.host == "0.0.0.0"
    # The port was not named in the environment, so the file still decides it.
    assert settings.port == 8000


def test_a_port_from_the_environment_becomes_a_number(tmp_path, monkeypatch):
    """The environment hands over text, but the server needs an integer."""
    monkeypatch.setenv("MCP_PORT", "9000")

    settings = load_settings(tmp_path / "absent.toml")

    assert settings.port == 9000
    assert isinstance(settings.port, int)


def test_mcp_url_is_built_from_the_other_settings():
    settings = Settings(host="0.0.0.0", port=9000, path="/mcp")

    assert settings.mcp_url() == "http://0.0.0.0:9000/mcp"


def test_a_relative_data_path_resolves_against_the_config_file(tmp_path):
    """Not against the working directory, which is why this is worth a test."""
    config_file = write_config(
        tmp_path,
        """
        [data]
        employees = "data/employees.json"
        """,
    )

    settings = load_settings(config_file)

    assert settings.employees_file == tmp_path / "data" / "employees.json"


def test_the_policies_file_comes_from_the_config_file(tmp_path):
    config_file = write_config(
        tmp_path,
        """
        [data]
        policies = "rules/policies.json"
        """,
    )

    settings = load_settings(config_file)

    assert settings.policies_file == tmp_path / "rules" / "policies.json"


def test_the_environment_beats_the_config_file_for_the_policies_file(tmp_path, monkeypatch):
    config_file = write_config(
        tmp_path,
        """
        [data]
        policies = "data/policies.json"
        """,
    )
    monkeypatch.setenv("MCP_POLICIES_FILE", "/srv/policies.json")

    settings = load_settings(config_file)

    assert settings.policies_file == Path("/srv/policies.json")


def test_the_review_queue_file_has_a_default(tmp_path):
    settings = load_settings(tmp_path / "absent.toml")

    assert settings.review_queue_file == REPO_ROOT / "review-queue" / "review_queue.jsonl"


def test_the_review_queue_file_comes_from_the_config_file(tmp_path):
    config_file = write_config(
        tmp_path,
        """
        [data]
        review_queue = "flags/queue.jsonl"
        """,
    )

    settings = load_settings(config_file)

    assert settings.review_queue_file == tmp_path / "flags" / "queue.jsonl"


def test_the_environment_beats_the_config_file_for_the_review_queue_file(tmp_path, monkeypatch):
    """How a container points the queue at a mounted volume."""
    config_file = write_config(
        tmp_path,
        """
        [data]
        review_queue = "review-queue/review_queue.jsonl"
        """,
    )
    monkeypatch.setenv("MCP_REVIEW_QUEUE_FILE", "/srv/review-queue/review_queue.jsonl")

    settings = load_settings(config_file)

    assert settings.review_queue_file == Path("/srv/review-queue/review_queue.jsonl")


def test_an_absolute_data_path_is_left_alone():
    resolved = resolve_path("/etc/employees.json", Path("/somewhere/else"))

    assert resolved == Path("/etc/employees.json")


def test_the_committed_config_file_loads():
    """A typo in config.toml should fail CI, not a live demo."""
    settings = load_settings(DEFAULT_CONFIG_FILE)

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.mcp_url() == "http://127.0.0.1:8000/mcp"
    # The paths in the committed file must point at the real data.
    assert settings.employees_file.exists()
    assert settings.policies_file.exists()
    # The queue file is written by the server, so it need not exist yet. It
    # must sit in the folder .gitignore leaves out, so flags are never committed.
    assert settings.review_queue_file == REPO_ROOT / "review-queue" / "review_queue.jsonl"
