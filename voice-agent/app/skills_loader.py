"""Discover and load @tool-decorated functions from skills directory.

Mirrors the shape of signal-bot-custom-skills: each skill is a subdirectory
containing skill.yaml (manifest) and one or more .py modules whose tools
are decorated with @strands.tool.
"""

import importlib.util
import logging
import sys
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def _load_module(skill_dir: Path, py_file: Path) -> object | None:
    mod_name = f"voice_skills.{skill_dir.name}.{py_file.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, py_file)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
        return module
    except Exception:
        logger.exception("Failed to load %s", py_file)
        return None


def _collect_tools(module: object) -> list:
    """Pick out functions that strands recognises as tools.

    strands marks decorated functions with a `TOOL_SPEC` attribute."""
    tools = []
    for name in dir(module):
        if name.startswith("_"):
            continue
        obj = getattr(module, name)
        if hasattr(obj, "TOOL_SPEC") or hasattr(obj, "tool_spec"):
            tools.append(obj)
    return tools


def discover(skills_dir: Path) -> tuple[list, list[str]]:
    """Return (tools, skill_names) discovered under skills_dir."""
    if not skills_dir.is_dir():
        logger.warning("Skills dir not found: %s", skills_dir)
        return [], []

    # Make the skills dir importable so `from skill_name import x` works
    # and shared helpers like mcp_client.py at the root are resolvable.
    if str(skills_dir) not in sys.path:
        sys.path.insert(0, str(skills_dir))

    tools: list = []
    names: list[str] = []

    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_") or entry.name.startswith("."):
            continue

        manifest_path = entry / "skill.yaml"
        manifest: dict = {}
        if manifest_path.exists():
            try:
                manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            except Exception:
                logger.exception("Bad manifest in %s", entry)
                continue

        if manifest.get("enabled") is False:
            continue

        skill_tools: list = []
        for py_file in entry.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            module = _load_module(entry, py_file)
            if module is not None:
                skill_tools.extend(_collect_tools(module))

        if skill_tools:
            tools.extend(skill_tools)
            names.append(manifest.get("name") or entry.name)
            logger.info("Loaded skill %s (%d tools)", entry.name, len(skill_tools))

    return tools, names
