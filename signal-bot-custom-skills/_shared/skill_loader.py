"""Collision-free sibling-module loader for custom skills.

The bot's registry loads each skill's entry point with a namespaced spec name
(``custom_skills.<skill>.<module>``), but bare ``import sibling`` calls inside
that entry point go through the regular import machinery and end up keyed in
``sys.modules`` under the bare name. Two skills with the same sibling filename
(e.g. both ``parse.py``) then alias to whichever loaded first — silently
calling the wrong skill's parser.

``load_sibling`` loads a sibling .py file from the caller's directory under a
namespaced ``sys.modules`` key, matching the registry's convention. No
``sys.path`` mutation, no collisions.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_sibling(skill_file: str, module_name: str) -> ModuleType:
    """Load ``<skill_file dir>/<module_name>.py`` namespaced by skill dir.

    Args:
        skill_file: Pass ``__file__`` from the calling skill module.
        module_name: Bare sibling module name, no ``.py``.

    Returns:
        The loaded module. Cached in ``sys.modules`` under
        ``custom_skills.<skill_dir>.<module_name>`` so repeat calls hit the
        cache (and so cross-references between siblings see the same instance).
    """
    skill_path = Path(skill_file).resolve()
    skill_dir = skill_path.parent
    spec_name = f"custom_skills.{skill_dir.name}.{module_name}"

    cached = sys.modules.get(spec_name)
    if cached is not None:
        return cached

    module_path = skill_dir / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(spec_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load sibling module {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec_name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_from_skill(other_skill_dir: Path | str, module_name: str) -> ModuleType:
    """Load ``<other_skill_dir>/<module_name>.py`` namespaced by that skill.

    For the rare case of one skill borrowing a module from another (e.g. roast
    using tts_clone's lang detector). Same namespacing rules as
    ``load_sibling``.
    """
    skill_dir = Path(other_skill_dir).resolve()
    spec_name = f"custom_skills.{skill_dir.name}.{module_name}"

    cached = sys.modules.get(spec_name)
    if cached is not None:
        return cached

    module_path = skill_dir / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(spec_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module {module_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec_name] = mod
    spec.loader.exec_module(mod)
    return mod
