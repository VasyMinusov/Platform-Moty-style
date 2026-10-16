"""
Роутер профиля CTF-платформы.

Регистрация и логин теперь на auth-service (/api/v1/auth/*).
Здесь остаётся только локальный профиль CTF: role, points, status,
is_blocked.

Все endpoints требуют валидный JWT от auth-service.
"""
from fastapi import APIRouter, Depends

from ..models import User
from ..schemas import UserOut
from ..security import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    """
    Текущий пользователь (локальный CTF-профиль).

    При первом запросе после регистрации в auth-service локальная
    запись создаётся автоматически (lazy provisioning в
    get_current_user).
    """
    return user