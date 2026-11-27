"""What "python -m it_equipment.evals" runs: load .env, then the eval runner.

Run it from the repository, with no server running: it builds its own inside
the process.

    python -m it_equipment.evals
    python -m it_equipment.evals --repeat 3

Every run makes paid calls to the model, and the scorecard says how many. It
reads the Foundry key, the resource name and the deployment name from .env by
itself, as the agent does. Never source .env into a terminal: Claude Code
reads ANTHROPIC_MODEL as well, and would pick up the deployment name as its own.
"""

import asyncio

from dotenv import load_dotenv

from it_equipment.config import REPO_ROOT
from it_equipment.evals.cli import main

if __name__ == "__main__":
    # .env is read here and in the agent's entry point, and nowhere else.
    # Loading it inside load_settings would let a real .env leak into the
    # tests; here it reaches only this process. The file beside config.toml is
    # named outright, and a variable already set in the environment wins.
    load_dotenv(REPO_ROOT / ".env")
    asyncio.run(main())
