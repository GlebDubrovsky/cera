"""Создаёт отдельные таблицы для остальных листов книги Vilmed."""

from alembic import op
import sqlalchemy as sa

revision = "0002_vilmed_workbook_tables"
down_revision = "0001_vilmed_reference_categories"
branch_labels = None
depends_on = None

SHEET_TABLES = {
    "vilmed_tag_tiles": ("link_text",),
    "vilmed_categories": (
        "category_name",
        "activity",
        "symbol_code",
        "element_count",
        "modified_at",
        "category_id",
        "level",
        "hide_from_menu_and_categories",
        "menu_name",
        "hide_only_from_menu",
    ),
    "vilmed_bar_tags": ("address", "h1", "main_category", "parent_category", "normal_form"),
    "vilmed_menu_categories": (
        "category_name",
        "activity",
        "symbol_code",
        "element_count",
        "modified_at",
        "category_id",
        "level",
        "hide_from_menu_and_categories",
        "menu_name",
        "hide_only_from_menu",
    ),
    "vilmed_products": (
        "product_name",
        "symbol_code",
        "description",
        "product_id",
        "sku",
        "package",
        "specifications",
        "keyword",
        "category",
    ),
}


def upgrade() -> None:
    """Добавляет пустые таблицы; существующие таблицы и данные не меняются."""
    for table_name, columns in SHEET_TABLES.items():
        op.create_table(
            table_name,
            sa.Column("row_id", sa.BigInteger(), autoincrement=True, nullable=False),
            *(sa.Column(column_name, sa.Text(), nullable=True) for column_name in columns),
            sa.PrimaryKeyConstraint("row_id"),
        )


def downgrade() -> None:
    """Удаляет только таблицы, добавленные этой миграцией, вместе с их данными."""
    for table_name in reversed(tuple(SHEET_TABLES)):
        op.drop_table(table_name)
