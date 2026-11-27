"""What "python -m it_equipment.agent" runs: load .env, then the agent.

Run it in a second terminal, with the server already running:

    python -m it_equipment.server   # terminal 1
    python -m it_equipment.agent    # terminal 2

It reads the Foundry key, the resource name and the deployment name from .env
by itself. Never source .env into a terminal: Claude Code reads
ANTHROPIC_MODEL as well, and would pick up the deployment name as its own.
"""

import asyncio

from dotenv import load_dotenv

from it_equipment.agent.cli import main
from it_equipment.config import REPO_ROOT

if __name__ == "__main__":
    # .env is read here and nowhere else. Loading it inside load_settings would
    # let a real .env leak into the tests; here it reaches only this process.
    # The file beside config.toml is named outright, rather than left to
    # python-dotenv's own search upwards from this file. A variable already
    # set in the environment wins over .env, which is python-dotenv's default.
    load_dotenv(REPO_ROOT / ".env")
    asyncio.run(main())
