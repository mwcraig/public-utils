import copy
import json
import re
import warnings
from pathlib import Path

import pytest

from aavso_starlist_schema import (
    _MIGRATIONS,
    SCHEMA_VERSION,
    NewerSchemaVersionError,
    SchemaMigrationWarning,
    StarListSet,
    UnsupportedSchemaVersionError,
    _generation,
    upgrade,
)

# One directory per migration step, named <old generation>_to_<new generation>,
# holding a before.json / after.json pair.
MIGRATION_DATA = Path(__file__).parent / "data" / "migrations"

LEGACY_VERSIONS = [None, "0.0.1.dev451+gde1568f", "0.1.dev66+g6f57c4d02", "0.0.0", "0.1.0"]


def _example_data(**overrides):
    """
    Build raw, unvalidated data for a star list set at the current version.

    Parameters
    ----------
    **overrides
        Top-level keys to set on the result, for example a different
        ``schema_version``.

    Returns
    -------
    dict
        The models' example values dumped to JSON-compatible types, with
        ``overrides`` applied: what ``upgrade()`` sees after ``json.loads``.
    """
    data = StarListSet.from_examples().model_dump(mode="json")
    data.update(overrides)
    return data


def _legacy_data(version):
    """
    Build example data as a pre-versioning file would present it.

    Parameters
    ----------
    version : str or None
        The legacy ``schema_version`` string to stamp, or ``None`` to omit
        the field entirely, as the oldest files did.

    Returns
    -------
    dict
        Raw starlist-set data carrying the legacy version.
    """
    data = _example_data()
    if version is None:
        del data["schema_version"]
    else:
        data["schema_version"] = version
    return data


def _next_generation_version():
    """
    Compute the first version of the generation after ``SCHEMA_VERSION``'s.

    Returns
    -------
    str
        The next minor while the schema is ``0.y.z``, and the next major from
        1.0.0 on, so the tests stay correct as ``SCHEMA_VERSION`` moves.
    """
    major, minor, _ = (int(part) for part in SCHEMA_VERSION.split("."))
    return f"0.{minor + 1}.0" if major == 0 else f"{major + 1}.0.0"


def _fixture_pair(generation):
    """
    Load the before/after fixture pair for the migration out of a generation.

    Parameters
    ----------
    generation : str
        The generation being left, a key of ``_MIGRATIONS``.

    Returns
    -------
    tuple of dict
        The parsed ``before.json`` and ``after.json`` from
        ``tests/data/migrations/<generation>_to_<target>/``.
    """
    target_generation = _generation(_MIGRATIONS[generation].target)
    directory = MIGRATION_DATA / f"{generation}_to_{target_generation}"
    return (
        json.loads((directory / "before.json").read_text()),
        json.loads((directory / "after.json").read_text()),
    )


@pytest.mark.parametrize("generation", sorted(_MIGRATIONS))
def test_each_migration_step_matches_its_fixture_pair(generation):
    # Every migration needs a fixture pair; a missing directory fails here.
    before, after = _fixture_pair(generation)
    step = _MIGRATIONS[generation]

    result = step.func(copy.deepcopy(before))
    result["schema_version"] = step.target

    assert result == after


@pytest.mark.parametrize("generation", sorted(_MIGRATIONS))
def test_fixture_files_upgrade_to_a_valid_current_file(generation):
    # Old files must stay readable however many generations later.
    before, _ = _fixture_pair(generation)

    with pytest.warns(SchemaMigrationWarning):
        upgraded = upgrade(before)

    assert StarListSet.model_validate(upgraded).schema_version == SCHEMA_VERSION


@pytest.mark.parametrize("version", LEGACY_VERSIONS)
def test_legacy_versions_are_upgraded_with_warning(version):
    # Every legacy version string, and a missing version, is upgraded to the
    # current version with exactly one warning.
    with pytest.warns(SchemaMigrationWarning) as record:
        result = upgrade(_legacy_data(version))

    # Exactly one warning, naming both ends of the migration and what changed.
    assert len(record) == 1
    message = str(record[0].message)
    assert ("missing" if version is None else version) in message
    assert SCHEMA_VERSION in message
    assert _MIGRATIONS["legacy"].summary in message

    assert result["schema_version"] == SCHEMA_VERSION


def test_current_version_is_returned_unchanged_without_warning():
    # Data already at the current version comes back as the same object, silently.
    data = _example_data(schema_version=SCHEMA_VERSION)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert upgrade(data) is data


@pytest.mark.parametrize("version", ["9.0.0", _next_generation_version()])
def test_newer_version_raises(version):
    # A version from a later generation is an error telling the user to upgrade
    # the package, not a validation error.
    with pytest.raises(NewerSchemaVersionError, match=re.escape(version)):
        upgrade(_example_data(schema_version=version))


@pytest.mark.parametrize("version", ["banana", 2, ["0.2.0"], "1.2"])
def test_unsupported_versions_raise(version):
    # Non-strings and strings that are neither X.Y.Z nor a legacy 0.x string are
    # rejected as uninterpretable.
    with pytest.raises(UnsupportedSchemaVersionError):
        upgrade(_example_data(schema_version=version))


def test_version_errors_are_not_value_errors():
    # Callers catching ValueError for validation problems must not swallow a
    # version problem.
    assert not issubclass(NewerSchemaVersionError, ValueError)
    assert not issubclass(UnsupportedSchemaVersionError, ValueError)


@pytest.mark.parametrize("version", LEGACY_VERSIONS)
def test_upgrade_does_not_mutate_input(version):
    # upgrade() returns a new dict and leaves the caller's data untouched.
    data = _legacy_data(version)
    snapshot = copy.deepcopy(data)
    with pytest.warns(SchemaMigrationWarning):
        result = upgrade(data)
    assert data == snapshot
    assert result is not data


def test_migration_chain_reaches_current_generation():
    # Following the migrations from the oldest generation must end at the
    # generation of SCHEMA_VERSION, with no gaps. This fails when a breaking
    # bump lands without its migration.
    strict_semver = re.compile(r"\d+\.\d+\.\d+")
    generation = "legacy"
    seen = set()
    while generation != _generation(SCHEMA_VERSION):
        assert generation not in seen, f"migration cycle at {generation!r}"
        seen.add(generation)
        assert generation in _MIGRATIONS, f"no migration out of generation {generation!r}"
        target = _MIGRATIONS[generation].target
        assert strict_semver.fullmatch(target)
        generation = _generation(target)

    # No migration should start from the current generation or beyond.
    assert _generation(SCHEMA_VERSION) not in _MIGRATIONS
    assert seen == set(_MIGRATIONS)


def test_from_json_upgrades_a_legacy_file():
    # A real legacy file loads through from_json, upgraded, with all of its star
    # lists and star items intact.
    before, _ = _fixture_pair("legacy")
    with pytest.warns(SchemaMigrationWarning):
        result = StarListSet.from_json(json.dumps(before))

    assert result.schema_version == SCHEMA_VERSION
    assert len(result.star_lists) == len(before["star_lists"])
    assert len(result.star_lists[0].staritems) == len(before["star_lists"][0]["staritems"])


def test_from_json_current_round_trip():
    # from_json on a current-version file is a plain parse: no warning, equal object.
    original = StarListSet.from_examples()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert StarListSet.from_json(original.model_dump_json()) == original
