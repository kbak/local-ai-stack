"""Load the tools explicitly enabled for browser voice in skill manifests."""

from pathlib import Path

from stack_shared.skills import discover as discover_skills


def discover(skills_dir: Path) -> tuple[list, list[str]]:
    return discover_skills(skills_dir, runtime='voice')
