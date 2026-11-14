"""Создаёт таблицу продуктов дерматологии и копирует в неё данные."""

from alembic import op
import sqlalchemy as sa

revision = "0003_vilmed_dermatology_products"
down_revision = "0002_vilmed_workbook_tables"
branch_labels = None
depends_on = None

PRODUCT_COLUMNS = (
    "product_name",
    "symbol_code",
    "description",
    "product_id",
    "sku",
    "package",
    "specifications",
    "keyword",
    "category",
)


def upgrade() -> None:
    """Создаёт отдельную таблицу и переносит в неё товары нужной категории."""
    op.create_table(
        "vilmed_dermatology_products",
        sa.Column("row_id", sa.BigInteger(), autoincrement=True, nullable=False),
        *(sa.Column(column_name, sa.Text(), nullable=True) for column_name in PRODUCT_COLUMNS),
        sa.PrimaryKeyConstraint("row_id"),
    )

    column_list = ", ".join(PRODUCT_COLUMNS)
    op.get_bind().execute(
        sa.text(
            f"INSERT INTO vilmed_dermatology_products ({column_list}) "
            f"SELECT {column_list} FROM vilmed_products "
            "WHERE category = :category"
        ),
        {"category": "Дерматология"},
    )


def downgrade() -> None:
    """Удаляет таблицу категории вместе с перенесёнными данными."""
    op.drop_table("vilmed_dermatology_products")
