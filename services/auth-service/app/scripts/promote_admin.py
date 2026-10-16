"""
CLI: повышение/понижение прав администратора.

Использование:
    python -m app.scripts.promote_admin --email admin@example.com
    python -m app.scripts.promote_admin --email admin@example.com --demote

Через Makefile:
    make promote-admin e=admin@example.com
    make demote-admin  e=admin@example.com

Зачем нужен CLI, а не API:
- Эндпоинта для самостоятельного повышения до админа нет и не должно
  быть: компрометация обычной сессии не должна давать возможность
  захвата админки.
- Первый админ создаётся оператором на сервере (SSH + доступ к БД).

Возвращает exit code:
- 0 — успех (или идемпотентный no-op).
- 1 — ошибка (пользователь не найден, БД недоступна).

Безопасность:
- Не логирует никаких данных, кроме email и результата.
- Не требует JWT_SECRET_KEY / ENCRYPTION_KEY — только доступ к БД
  (через Settings.postgres_*).

Функция `promote_user` экспортируется отдельно — её использует
`tests/test_admin.py` без запуска CLI-обёртки (чтобы не создавать
отдельную engine).
"""

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import dispose_engine, get_session_factory
from app.models import User


async def promote_user(
    session: AsyncSession,
    email: str,
    *,
    demote: bool = False,
) -> tuple[bool, str]:
    """
    Установить is_admin для пользователя.

    Возвращает (success, message).
    - success=True при успехе или идемпотентном no-op (уже с таким флагом).
    - success=False при ошибке (пользователь не найден).

    НЕ коммитит — это ответственность вызывающего кода.
    """
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        return False, f"User not found: {email}"

    new_value = not demote
    if user.is_admin == new_value:
        action = "demote" if demote else "promote"
        return True, f"No-op: user {email} is already is_admin={new_value} ({action})."

    user.is_admin = new_value
    await session.flush()

    action = "demoted" if demote else "promoted"
    return True, f"User {email} {action}: is_admin={new_value}."


async def _run(email: str, demote: bool) -> int:
    """CLI-обёртка: session + commit + dispose."""
    factory = get_session_factory()
    try:
        async with factory() as session:
            success, message = await promote_user(session, email, demote=demote)
            if success:
                await session.commit()
            print(message)
            return 0 if success else 1
    finally:
        await dispose_engine()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.promote_admin",
        description=(
            "Promote or demote a user's admin flag. "
            "Useful for bootstrapping the first admin."
        ),
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Email of the user to promote/demote.",
    )
    parser.add_argument(
        "--demote",
        action="store_true",
        help="Demote instead of promote (revoke admin rights).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.email, args.demote))


if __name__ == "__main__":
    sys.exit(main())
