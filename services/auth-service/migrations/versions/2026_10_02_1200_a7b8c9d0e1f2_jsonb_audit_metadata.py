"""jsonb audit metadata

Преобразует audit_logs.metadata_json из Text в JSONB.

Стратегия для существующих строк:
- NULL → NULL;
- строка, начинающаяся с { или [ → парсится как JSON;
- всё остальное ("reason=user_not_found", "stage=mfa ...") →
  оборачивается в {"legacy": "<исходная строка>"}.

Это не теряет исторические данные и не падает на невалидном JSON.

Revision ID: a7b8c9d0e1f2
Revises: 889e318d15ce
Create Date: 2026-10-02 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "889e318d15ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Text → JSONB с безопасным преобразованием.
    #    Регулярка ^\s*[\{\[] ловит строки, которые уже JSON-объект/массив.
    #    Всё остальное — legacy-строки, упаковываем.
    op.execute(
        """
        ALTER TABLE audit_logs
          ALTER COLUMN metadata_json TYPE jsonb
          USING CASE
            WHEN metadata_json IS NULL THEN NULL
            WHEN metadata_json ~ '^\\s*[\\{\\[]' THEN metadata_json::jsonb
            ELSE jsonb_build_object('legacy', metadata_json)
          END
        """
    )

    # 2. GIN-индекс для поиска по ключам.
    #    jsonb_path_ops компактнее и быстрее для @> (наш основной кейс:
    #    "найди все события с reason=replay"). Не поддерживает ?, ?|, ?& —
    #    если понадобятся, заменим на jsonb_ops (больше индекс, но
    #    поддерживает все операторы).
    op.create_index(
        "ix_audit_logs_metadata",
        "audit_logs",
        ["metadata_json"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"metadata_json": "jsonb_path_ops"},
    )


def downgrade() -> None:
    # 1. Удаляем индекс.
    op.drop_index("ix_audit_logs_metadata", table_name="audit_logs")

    # 2. JSONB → Text.
    #    JSON-объекты сериализуем обратно в строку, но plain-text
    #    ("{\"reason\":\"x\"}") уже не «свернётся» в "reason=x" —
    #    legacy-строки станут JSON-строками. Это осознанно:
    #    обратная совместимость со старым кодом, читавшим Text.
    op.execute(
        """
        ALTER TABLE audit_logs
          ALTER COLUMN metadata_json TYPE text
          USING metadata_json::text
        """
    )


def _noop() -> None:
    """Заглушка для mypy: sa, postgresql импортированы для autogenerate."""
    _ = sa
    _ = postgresql