"""
Every schema version is archived unchanged under
``aavso_starlist_schema_data/v<version>/``; that directory is the record of what each version looked like. The current reference
files must match the archive for ``SCHEMA_VERSION``, so changing the schema
without bumping the version fails here. CI separately rejects a pull request
that modifies or deletes an archived file.

The frozen models of earlier generations are held to the same archive, so a
frozen model cannot change either.
"""

import json
import warnings

import pytest

from aavso_starlist_schema import (
    _MIGRATIONS,
    _RELEASED_VERSIONS,
    DATA_DIR,
    SCHEMA_VERSION,
    StarListSet,
    _generation,
    _parse_semver,
)

REFERENCE_FILES = ("schema_definition.json", "schema_definition.md")


def archived_versions():
    """
    Find every archived schema version under ``DATA_DIR``.

    Returns
    -------
    list of tuple
        ``(version, directory)`` pairs, where ``version`` is a tuple of ints
        parsed from the ``v<version>/`` directory name. Sorted oldest
        first, so the last entry is the newest archive.
    """
    found = []
    for directory in DATA_DIR.glob("v*"):
        if directory.is_dir():
            version = _parse_semver(directory.name[1:])
            assert version is not None, f"{DATA_DIR.name}/{directory.name} is not named v<X.Y.Z>"
            found.append((version, directory))
    return sorted(found)


@pytest.mark.parametrize("name", REFERENCE_FILES)
def test_current_schema_matches_its_archive(name):
    # The generated reference file must be identical to the archived copy for
    # SCHEMA_VERSION, so a schema change without a version bump fails here.
    archived = DATA_DIR / f"v{SCHEMA_VERSION}" / name
    assert archived.is_file(), (
        f"No archive for schema version {SCHEMA_VERSION}; run `uv run poe archive`."
    )
    assert (DATA_DIR / name).read_text() == archived.read_text(), (
        f"The reference {name} differs from the archived {SCHEMA_VERSION} schema. If the "
        "schema changed, bump SCHEMA_VERSION, then run `uv run poe generate` "
        "and `uv run poe archive`."
    )


def test_archives_are_complete_and_state_their_version():
    # Every archive directory holds both reference files, and the JSON's version
    # key matches the directory name.
    for _, directory in archived_versions():
        for name in REFERENCE_FILES:
            assert (directory / name).is_file(), f"{directory.name} is missing {name}"
        schema = json.loads((directory / "schema_definition.json").read_text())
        assert schema["version"] == directory.name[1:]


def test_current_version_is_the_newest_archived():
    # Guards against lowering SCHEMA_VERSION, or forgetting to bump it past an
    # archive that already exists.
    newest, _ = max(archived_versions())
    assert newest == _parse_semver(SCHEMA_VERSION)


def _generation_archive(generation):
    """
    Find the archived JSON schema that a generation's frozen model must match.

    Parameters
    ----------
    generation : str
        A generation that has been left, a key of ``_MIGRATIONS``.

    Returns
    -------
    pathlib.Path
        ``legacy/schema_definition.json`` under ``DATA_DIR`` for the legacy
        generation, otherwise the file from the newest ``v<version>/`` whose version
        is in ``generation``.
    """
    if generation == "legacy":
        return DATA_DIR / "legacy" / "schema_definition.json"
    _, directory = max(
        (version, directory)
        for version, directory in archived_versions()
        if _generation(directory.name[1:]) == generation
    )
    return directory / "schema_definition.json"


@pytest.mark.parametrize("generation", _MIGRATIONS)
def test_frozen_model_matches_its_archive(generation):
    # The frozen model of a generation must generate exactly the archived
    # schema of that generation. This is what keeps a frozen model frozen: any
    # edit to it, or to code it shares with the live models, fails here.
    frozen = _MIGRATIONS[generation].model
    generated = json.dumps(frozen.model_json_schema(), indent=2)

    assert generated == _generation_archive(generation).read_text()


def test_released_versions_match_the_archives():
    # The reader takes its list of released versions from a constant rather
    # than the filesystem, so the constant must name exactly the archived
    # versions, oldest first.
    archived = [directory.name[1:] for _, directory in archived_versions()]

    assert list(_RELEASED_VERSIONS) == archived, (
        "_RELEASED_VERSIONS in aavso_starlist_schema.py must list exactly the "
        f"versions archived under {DATA_DIR.name}/, oldest first."
    )


@pytest.mark.parametrize(
    "directory",
    [
        directory
        for _, directory in archived_versions()
        if _generation(directory.name[1:]) == _generation(SCHEMA_VERSION)
    ],
    ids=lambda directory: directory.name,
)
def test_archived_version_of_current_generation_is_read_as_current(directory):
    # Every released version of the current generation is read without
    # migration, so without a warning, and the object states the current
    # version, so a file written from it is labelled with the schema it
    # conforms to.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        star_list_set = StarListSet.model_validate(
            {"schema_version": directory.name[1:], "star_lists": []}
        )

    assert star_list_set.schema_version == SCHEMA_VERSION
