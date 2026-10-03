#!/usr/bin/env python3
"""Render host-specific systemd units without installing or starting them."""

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def render(template: str, root: Path) -> str:
    value = str(root.resolve())
    if "\n" in value or "\r" in value:
        raise ValueError("Installation path must not contain a newline")
    # Templates quote complete paths. Escape systemd strings and specifiers.
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return template.replace("@STACK_ROOT@", value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/systemd")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for template in sorted((ROOT / "config/systemd").glob("*.service")):
        target = args.output / template.name
        target.write_text(render(template.read_text(), args.root))
        print(target)


if __name__ == "__main__":
    main()
