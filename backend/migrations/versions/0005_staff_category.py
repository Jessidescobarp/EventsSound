"""Add the `staff` equipment category (people services) to the category CHECK constraint.

Revision ID: 0005
Revises: 0004

`category` is VARCHAR(16) + CHECK, not a native ENUM, so only the constraint changes. The value
lists are literal so this revision stays frozen history. Postgres DDL is transactional: the drop
and the re-create commit together, so there is no window without the constraint. The table has a
few dozen rows, so re-validating it is instant. Staff rows themselves are loaded by the seed CLI,
never by this migration. Downgrade refuses to run while staff rows exist, because the old
constraint would reject them and deleting data (rows referenced by packages and bookings) from a
migration is not safe; remove those rows deliberately first.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "ck_equipment_items_category_valid"
_OLD = "category IN ('sound', 'lighting', 'dj', 'stage', 'effects', 'video')"
_NEW = "category IN ('sound', 'lighting', 'dj', 'stage', 'effects', 'video', 'staff')"


def _replace_constraint(condition: str) -> None:
    op.drop_constraint(op.f(_NAME), "equipment_items", type_="check")
    op.create_check_constraint(op.f(_NAME), "equipment_items", condition)


def upgrade() -> None:
    _replace_constraint(_NEW)


def downgrade() -> None:
    staff_rows = op.get_bind().exec_driver_sql(
        "SELECT count(*) FROM equipment_items WHERE category = 'staff'"
    )
    if staff_rows.scalar_one():
        raise RuntimeError("cannot downgrade 0005: staff equipment rows exist; remove them first")
    _replace_constraint(_OLD)
