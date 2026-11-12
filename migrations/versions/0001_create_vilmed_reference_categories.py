"""Создаёт таблицу справочника категорий Vilmed."""

from alembic import op
import sqlalchemy as sa

revision = "0001_vilmed_reference_categories"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vilmed_reference_categories",
        sa.Column("row_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("row_id"),
    )


def downgrade() -> None:
    op.drop_table("vilmed_reference_categories")
