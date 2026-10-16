"""Portfolio events, editable by an admin and shown on the public portfolio page.

Revision ID: 0008
Revises: 0007

A plain CREATE TABLE of a new table, seeded with the six illustrative events the site showed as
fixed text until now (synthetic, no real clients). Names are literal so this revision stays
frozen history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVENTS = [
    (
        "Boda en jardín",
        "Boda",
        "Ceremonia y recepción para 180 invitados con sonido ambiental y pista de baile iluminada.",
        ["Sonido", "Micrófonos inalámbricos", "Luces LED"],
    ),
    (
        "Lanzamiento corporativo",
        "Corporativo",
        "Presentación de producto con pantalla LED, micrófonos de solapa y escenario modular.",
        ["Pantalla LED", "Consola de mezcla", "Tarima"],
    ),
    (
        "Festival universitario",
        "Festival",
        "Dos escenarios con bandas en vivo y DJs durante un día completo.",
        ["Sistema de sonido", "Cabezas móviles", "Efectos"],
    ),
    (
        "Noche de DJ en terraza",
        "DJ",
        "Sesión nocturna al aire libre con cabina de DJ, láser y máquina de humo.",
        ["Equipo de DJ", "Láser", "Humo"],
    ),
    (
        "Fiesta de quince años",
        "Fiesta",
        "Vals, baile sorpresa y pista con efectos de chispas frías.",
        ["Sonido", "Chispas frías", "Luces LED"],
    ),
    (
        "Concierto en teatro",
        "Concierto",
        "Montaje de sonido e iluminación para un concierto acústico con aforo de 400 personas.",
        ["Line array", "Monitores", "Iluminación escénica"],
    ),
]


def upgrade() -> None:
    table = op.create_table(
        "portfolio_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("equipment", postgresql.JSONB(), nullable=False),
        sa.Column("visible", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_events")),
        sa.CheckConstraint(
            "jsonb_typeof(equipment) = 'array'", name=op.f("ck_portfolio_events_equipment_array")
        ),
    )
    op.bulk_insert(
        table,
        [
            {"title": title, "kind": kind, "description": description, "equipment": equipment}
            for title, kind, description, equipment in EVENTS
        ],
    )


def downgrade() -> None:
    op.drop_table("portfolio_events")
