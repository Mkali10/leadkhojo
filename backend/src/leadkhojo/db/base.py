"""Declarative base, naming conventions and shared column types.

The schema targets PostgreSQL. Tests run against SQLite, which is why the
JSON and UUID columns use dialect variants rather than Postgres-only types
directly — the production column is JSONB, the test column is JSON, and the
model code does not care.

What that portability does NOT cover, and must be verified against a real
PostgreSQL before production:
  * FOR UPDATE SKIP LOCKED in the job queue (SQLite has no row locking)
  * JSONB containment/path operators, if we ever query inside a snapshot
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

# Explicit constraint naming. Without this, Alembic autogenerate produces
# unnamed constraints that cannot be dropped in a later migration.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s__%(column_0_N_name)s",
    "uq": "uq_%(table_name)s__%(column_0_N_name)s",
    "ck": "ck_%(table_name)s__%(constraint_name)s",
    "fk": "fk_%(table_name)s__%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}

# JSONB on PostgreSQL, plain JSON everywhere else.
JsonColumn = JSON().with_variant(JSONB(), "postgresql")

# SQLAlchemy 2.0's Uuid renders as native uuid on PostgreSQL and CHAR(32)
# elsewhere, so the model declares one type and both dialects work.
UuidColumn = Uuid(as_uuid=True)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {
        dict[str, Any]: JsonColumn,
        list[Any]: JsonColumn,
    }


class UuidPrimaryKey:
    """UUID primary keys throughout.

    Non-enumerable, and they let a caller construct an object graph before
    anything is flushed — which the pipeline relies on.
    """

    id: Mapped[uuid.UUID] = mapped_column(UuidColumn, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
