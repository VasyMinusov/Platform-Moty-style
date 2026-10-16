"""
Тест формата PHC-строки парольного хеша.

Фиксирует, что PasswordHasher выдаёт именно Argon2id
(а не Argon2i / Argon2d / bcrypt / scrypt).

Мотивация: argon2-cffi по умолчанию использует Type.ID, но мы не
хотим зависеть от дефолтов. Если кто-то изменит параметры hasher'а
или обновит argon2-cffi с другим дефолтом — тест упадёт.
"""

from app.security.passwords import (
    ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    PasswordHasher,
)


def test_hash_uses_argon2id() -> None:
    """PHC-строка начинается с $argon2id$ — это Argon2id, не i/d."""
    hasher = PasswordHasher()
    phc = hasher.hash("some-very-long-password-15chars")

    assert phc.startswith("$argon2id$"), (
        f"Ожидался Argon2id, получено: {phc.split('$')[1] if '$' in phc else phc}"
    )


def test_hash_parameters_match_config() -> None:
    """Параметры в PHC-строке совпадают с константами."""
    hasher = PasswordHasher()
    phc = hasher.hash("some-very-long-password-15chars")

    # Формат: $argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>
    params = phc.split("$")[3]
    # params = "m=65536,t=3,p=4"
    parts = dict(p.split("=") for p in params.split(","))

    assert int(parts["m"]) == ARGON2_MEMORY_COST
    assert int(parts["t"]) == ARGON2_TIME_COST
    assert int(parts["p"]) == ARGON2_PARALLELISM


def test_verify_works_roundtrip() -> None:
    """hash → verify возвращает True для правильного пароля."""
    hasher = PasswordHasher()
    password = "correct horse battery staple nist"
    phc = hasher.hash(password)

    assert hasher.verify(password, phc) is True


def test_verify_rejects_wrong_password() -> None:
    """hash → verify с неверным паролем возвращает False."""
    hasher = PasswordHasher()
    phc = hasher.hash("correct horse battery staple nist")

    assert hasher.verify("wrong-password", phc) is False


def test_needs_rehash_returns_false_for_current_params() -> None:
    """Хеш, созданный текущими параметрами, не требует rehash."""
    hasher = PasswordHasher()
    phc = hasher.hash("correct horse battery staple nist")

    assert hasher.needs_rehash(phc) is False