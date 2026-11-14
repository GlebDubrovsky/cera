"""Добавляет поля анализа к товарам Vilmed."""

from alembic import op
import sqlalchemy as sa

revision = "0004_vilmed_analysis_fields"
down_revision = "0003_vilmed_dermatology_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавляет необязательные текстовые поля для анализа товаров."""
    op.add_column("vilmed_description_products", sa.Column("important_words", sa.Text(), nullable=True))
    op.add_column("vilmed_description_products", sa.Column("prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    """Удаляет поля анализа при откате миграции."""
    op.drop_column("vilmed_description_products", "prompt")
    op.drop_column("vilmed_description_products", "important_words")
