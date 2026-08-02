"""Migration tests.

A migration that has never been run is a migration that does not work. These
apply the real chain to a real (SQLite) database and compare the result
against the models, which catches the failure mode that actually bites:
someone edits a model and forgets to generate the migration.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from leadkhojo.db import models  # noqa: F401  - registers tables on Base.metadata
from leadkhojo.db.base import Base

BACKEND_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "scans",
    "businesses",
    "site_snapshots",
    "findings",
    "opportunities",
    "business_scores",
    "reports",
    "jobs",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
def migrated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Apply the full migration chain to a fresh database."""
    db_path = tmp_path / "migrated.db"
    async_url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("LK_DATABASE_URL", async_url)

    from leadkhojo.core.config import get_settings

    get_settings.cache_clear()
    try:
        command.upgrade(_alembic_config(async_url), "head")
    finally:
        get_settings.cache_clear()

    return f"sqlite:///{db_path}"


def test_the_migration_chain_applies_cleanly(migrated_db: str) -> None:
    engine = create_engine(migrated_db)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert tables >= EXPECTED_TABLES, f"missing: {EXPECTED_TABLES - tables}"


def test_the_migration_matches_the_models(migrated_db: str) -> None:
    """The check that stops a model edit shipping without a migration.

    If this fails, someone changed models.py and did not run
    `alembic revision --autogenerate`.
    """
    engine = create_engine(migrated_db)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True, "include_object": _ignore_alembic_version},
            )
            differences = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert not differences, (
        "The schema and the models have diverged. Run:\n"
        "  alembic revision --autogenerate -m 'describe the change'\n\n"
        f"Differences: {differences}"
    )


def test_the_migration_is_reversible(migrated_db: str, tmp_path: Path) -> None:
    """Downgrade is what makes a bad deploy recoverable rather than an
    incident."""
    config = _alembic_config(migrated_db.replace("sqlite:///", "sqlite+aiosqlite:///"))

    command.downgrade(config, "base")

    engine = create_engine(migrated_db)
    try:
        remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()

    assert not remaining, f"downgrade left tables behind: {remaining}"


def test_indexes_the_hot_queries_need_exist(migrated_db: str) -> None:
    """Each of these backs a query the product runs constantly. A missing
    one is a slow scan list nobody attributes to the right cause."""
    engine = create_engine(migrated_db)
    try:
        inspector = inspect(engine)
        job_indexes = {i["name"] for i in inspector.get_indexes("jobs")}
        business_indexes = {i["name"] for i in inspector.get_indexes("businesses")}
        scan_indexes = {i["name"] for i in inspector.get_indexes("scans")}
    finally:
        engine.dispose()

    assert "ix_jobs__claimable" in job_indexes  # the job-claim access path
    assert "ix_businesses__scan_status" in business_indexes  # progress counting
    assert "ix_scans__status_created" in scan_indexes  # scan history listing


def test_the_dedup_constraint_survives_migration(migrated_db: str) -> None:
    engine = create_engine(migrated_db)
    try:
        constraints = {c["name"] for c in inspect(engine).get_unique_constraints("businesses")}
    finally:
        engine.dispose()

    assert "uq_businesses__scan_id_domain" in constraints or any(
        "domain" in (name or "") for name in constraints
    ), f"deduplication constraint missing: {constraints}"


def _ignore_alembic_version(
    obj: object, name: str, type_: str, reflected: bool, compare_to: object
) -> bool:
    return not (type_ == "table" and name == "alembic_version")


def test_asyncio_is_available_for_the_async_env() -> None:
    """env.py runs migrations through asyncio.run; guard the import path."""
    assert asyncio.get_event_loop_policy() is not None
