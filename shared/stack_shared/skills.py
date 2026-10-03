"""Manifest-based discovery shared by Signal and browser voice clients."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
import sys

import yaml

log = logging.getLogger(__name__)


def read_manifest(skill_dir: Path, runtime: str) -> dict | None:
    """Read a declared skill, skipping disabled or incompatible runtimes."""
    path = skill_dir / 'skill.yaml'
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('name'), str):
        raise ValueError(f'{path}: a skill name is required')
    runtimes = data.get('runtimes', ['signal', 'voice'])
    if not isinstance(runtimes, list) or any(r not in ('signal', 'voice') for r in runtimes):
        raise ValueError(f'{path}: runtimes must list signal and/or voice')
    if data.get('enabled') is False or runtime not in runtimes:
        return None
    refs = data.get('tools', [])
    if not isinstance(refs, list):
        raise ValueError(f'{path}: tools must be a list of module:function references')
    for ref in refs:
        _tool_parts(ref)
    return data


def _tool_parts(reference: str) -> tuple[str, str]:
    parts = reference.split(':') if isinstance(reference, str) else []
    if len(parts) != 2 or not all(p.isidentifier() and not p.startswith('_') for p in parts):
        raise ValueError(f'Invalid tool reference: {reference!r}')
    return parts[0], parts[1]


def load_tool(skill_dir: Path, reference: str):
    """Load only a manifest-declared tool, caching modules under the skill name."""
    module_name, function_name = _tool_parts(reference)
    skill_dir = skill_dir.resolve()
    # Existing sibling helpers import from this root. Never add an individual
    # skill directory: multiple skills have siblings with the same filename.
    root = str(skill_dir.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    name = f'custom_skills.{skill_dir.name}.{module_name}'
    path = skill_dir / f'{module_name}.py'
    module = sys.modules.get(name)
    if module is None or Path(module.__file__).resolve() != path:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f'Cannot load {path}')
        module = importlib.util.module_from_spec(spec)
        previous = sys.modules.get(name)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
            raise
    tool = getattr(module, function_name)
    if not callable(tool) or not (hasattr(tool, 'tool_spec') or hasattr(tool, 'TOOL_SPEC')):
        raise TypeError(f'{reference} is not a decorated tool')
    return tool


def discover(skills_dir: Path, runtime: str) -> tuple[list, list[str]]:
    """Return tools and skill names in manifest order, isolating load failures."""
    tools, names = [], []
    if not skills_dir.is_dir():
        return tools, names
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith(('_', '.')):
            continue
        try:
            manifest = read_manifest(entry, runtime)
        except Exception:
            log.exception('Failed to read skill manifest: %s', entry)
            continue
        if manifest is None:
            continue
        loaded = []
        for ref in manifest.get('tools', []):
            try:
                loaded.append(load_tool(entry, ref))
            except Exception:
                log.exception('Failed to load tool %s from %s', ref, entry.name)
        if loaded:
            tools.extend(loaded)
            names.append(manifest['name'])
            log.info('Loaded skill %s (%d tools)', entry.name, len(loaded))
    return tools, names
