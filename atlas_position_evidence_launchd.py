#!/usr/bin/env python3
"""Load only MASSIVE_API_KEY from Atlas profile env and exec with a minimal env."""
import os
import sys
from pathlib import Path

DEFAULT_ORCHESTRATOR = Path("/Users/yasser/scripts/atlas_position_evidence_orchestrator.py")
DEFAULT_ENV_FILE = Path("/Users/yasser/.hermes/profiles/atlas/.env")
KEY = "MASSIVE_API_KEY"
ALLOWED_CHILD_NAMES = {"HOME", "PATH", KEY}
ALLOWED_EVIDENCE_PREFIX = "ATLAS_POSITION_EVIDENCE_"


def load_massive_key(env_file: Path) -> str:
    """Parse exactly one single-line MASSIVE_API_KEY assignment; never source the file."""
    if not env_file.is_file():
        raise RuntimeError("Atlas profile env file unavailable")
    found = []
    with env_file.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("export "):
                stripped = stripped[7:].lstrip()
            if not stripped.startswith(KEY + "="):
                continue
            value = stripped[len(KEY) + 1 :]
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if not value or "\x00" in value or "\n" in value or "\r" in value:
                raise RuntimeError("MASSIVE_API_KEY assignment is empty or invalid")
            found.append(value)
    if len(found) != 1:
        raise RuntimeError("expected exactly one MASSIVE_API_KEY assignment")
    return found[0]


def child_environment(key: str) -> dict[str, str]:
    env = {
        "HOME": str(Path.home()),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        KEY: key,
    }
    for name, value in os.environ.items():
        if name.startswith(ALLOWED_EVIDENCE_PREFIX):
            env[name] = value
    return env


def main() -> int:
    env_file = Path(os.environ.get("ATLAS_POSITION_EVIDENCE_ENV_FILE", str(DEFAULT_ENV_FILE)))
    orchestrator = Path(os.environ.get("ATLAS_POSITION_EVIDENCE_ORCHESTRATOR", str(DEFAULT_ORCHESTRATOR)))
    try:
        key = load_massive_key(env_file)
        if not orchestrator.is_file():
            raise RuntimeError("orchestrator is not a regular file")
    except (OSError, RuntimeError) as exc:
        print(f"ERROR_PROVIDER_AUTH: {exc}", file=sys.stderr)
        return 78
    os.execve(sys.executable, [sys.executable, str(orchestrator)], child_environment(key))
    return 70


if __name__ == "__main__":
    raise SystemExit(main())
