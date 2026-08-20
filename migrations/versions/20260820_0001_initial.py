"""Create events, tickets, and sync metadata tables.

Revision ID: 20260820_0001
Revises:
Create Date: 2026-08-20 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("place_id", sa.String(length=255), nullable=False),
        sa.Column("place_name", sa.String(length=500), nullable=False),
        sa.Column("place_city", sa.String(length=255), nullable=False),
        sa.Column("place_address", sa.String(length=1000), nullable=False),
        sa.Column("place_seats_pattern", sa.Text(), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registration_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("number_of_visitors", sa.Integer(), nullable=False),
        sa.Column("provider_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index("ix_events_event_time_id", "events", ["event_time", "id"])
    op.create_index(op.f("ix_events_status"), "events", ["status"])

    op.create_table(
        "sync_metadata",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("last_sync_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sync_status",
            sa.String(length=32),
            server_default="never",
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_metadata")),
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("first_name", sa.String(length=255), nullable=False),
        sa.Column("last_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("seat", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_tickets_event_id_events"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets")),
    )
    op.create_index(op.f("ix_tickets_email"), "tickets", ["email"])
    op.create_index(op.f("ix_tickets_event_id"), "tickets", ["event_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_tickets_event_id"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_email"), table_name="tickets")
    op.drop_table("tickets")
    op.drop_table("sync_metadata")
    op.drop_index(op.f("ix_events_status"), table_name="events")
    op.drop_index("ix_events_event_time_id", table_name="events")
    op.drop_table("events")
