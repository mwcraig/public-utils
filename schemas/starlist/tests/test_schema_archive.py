"""
Every schema version is archived unchanged under ``data/v<version>/``; that
directory is the record of what each version looked like. The current reference
files must match the archive for ``SCHEMA_VERSION``, so changing the schema
without bumping the version fails here. CI separately rejects a pull request
that modifies or deletes an archived file.
"""

import json

import pytest

from aavso_starlist_schema import DATA_DIR, SCHEMA_VERSION

REFERENCE_FILES = ("schema_definition.json", "schema_definition.md")


def archived_versions():
    """Archived versions as ``(version tuple, directory)``, oldest first."""
    found = []
    for directory in DATA_DIR.glob("v*"):
        if directory.is_dir():
            version = tuple(int(part) for part in directory.name[1:].split("."))
            found.append((version, directory))
    return sorted(found)


@pytest.mark.parametrize("name", REFERENCE_FILES)
def test_current_schema_matches_its_archive(name):
    archived = DATA_DIR / f"v{SCHEMA_VERSION}" / name
    assert archived.is_file(), (
        f"No archive for schema version {SCHEMA_VERSION}; run `uv run poe archive`."
    )
    assert (DATA_DIR / name).read_text() == archived.read_text(), (
        f"data/{name} differs from the archived {SCHEMA_VERSION} schema. If the "
        "schema changed, bump SCHEMA_VERSION, then run `uv run poe generate` "
        "and `uv run poe archive`."
    )


def test_archives_are_complete_and_state_their_version():
    for _, directory in archived_versions():
        for name in REFERENCE_FILES:
            assert (directory / name).is_file(), f"{directory.name} is missing {name}"
        schema = json.loads((directory / "schema_definition.json").read_text())
        assert schema["version"] == directory.name[1:]


def test_current_version_is_the_newest_archived():
    # Guards against lowering SCHEMA_VERSION, or forgetting to bump it past an
    # archive that already exists.
    newest = archived_versions()[-1][1].name[1:]
    assert newest == SCHEMA_VERSION
