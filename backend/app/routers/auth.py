from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import UserCreate, UserOut, Token
from ..security import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(400, "Username already taken")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(400, "Email already registered")

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    if getattr(user, "is_blocked", False):
        raise HTTPException(403, "Account is blocked")
    token = create_access_token(subject=user.username)
    return Token(access_token=token)


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    """Возвращает текущего авторизованного пользователя.
    Email возвращается как строка — чтобы невалидные адреса из старых записей
    не ломали ответ."""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role.value if hasattr(user.role, 'value') else str(user.role),
        "points": user.points,
        "status": user.status,
        "is_blocked": bool(getattr(user, "is_blocked", False)),
    }

