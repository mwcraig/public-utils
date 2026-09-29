"""Fail if the generated schema changed relative to a base ref without a version bump.

Run from ``schemas/starlist`` (``uv run poe check-schema-version --base origin/main``).
Only the standard library is used so this can run before the package is installed.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DATA_DIR = HERE / "data"
JSON_NAME = "schema_definition.json"
MD_NAME = "schema_definition.md"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=HERE, text=True)


def base_file(ref: str, name: str) -> str | None:
    """Contents of ``data/<name>`` at ``ref``, or ``None`` if it does not exist there."""
    toplevel = Path(git("rev-parse", "--show-toplevel").strip())
    rel = (DATA_DIR / name).relative_to(toplevel).as_posix()
    try:
        return git("show", f"{ref}:{rel}")
    except subprocess.CalledProcessError:
        return None


def schema_version(schema: dict) -> str:
    return schema["properties"]["schema_version"]["default"]


def without_version(schema: dict) -> dict:
    """The schema with everything that depends on SCHEMA_VERSION removed."""
    stripped = copy.deepcopy(schema)
    field = stripped["properties"]["schema_version"]
    field.pop("default", None)
    field.pop("examples", None)
    return stripped


def markdown_without_version(markdown: str) -> str:
    """The markdown with the schema_version table row removed."""
    return "\n".join(
        line for line in markdown.splitlines() if "| schema_version |" not in line
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="origin/main",
        help="git ref to compare the generated schema against (default: origin/main)",
    )
    args = parser.parse_args(argv)

    base_json = base_file(args.base, JSON_NAME)
    base_md = base_file(args.base, MD_NAME)
    if base_json is None or base_md is None:
        print(f"No reference schema files found at {args.base}; nothing to compare.")
        return 0

    base_schema = json.loads(base_json)
    current_schema = json.loads((DATA_DIR / JSON_NAME).read_text())
    current_md = (DATA_DIR / MD_NAME).read_text()

    base_version = schema_version(base_schema)
    current_version = schema_version(current_schema)

    schema_changed = without_version(base_schema) != without_version(current_schema) or (
        markdown_without_version(base_md) != markdown_without_version(current_md)
    )

    if schema_changed and base_version == current_version:
        print(
            f"ERROR: the generated schema differs from {args.base} but SCHEMA_VERSION "
            f"is still {current_version!r}.\n"
            "Bump SCHEMA_VERSION in aavso_starlist_schema.py and run `uv run poe generate`.",
            file=sys.stderr,
        )
        return 1

    if schema_changed:
        print(f"Schema changed and SCHEMA_VERSION bumped: {base_version} -> {current_version}.")
    elif base_version != current_version:
        print(
            f"Note: SCHEMA_VERSION bumped ({base_version} -> {current_version}) "
            "but the generated schema is otherwise unchanged."
        )
    else:
        print(f"Generated schema unchanged from {args.base}; SCHEMA_VERSION {current_version} is fine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
