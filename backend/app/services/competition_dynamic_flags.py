"""Генерация динамических флагов для заданий соревнования.

Стратегии:
- static      — флаг из манифеста (используется ch.flag_hash)
- per_user    — флаг на пользователя
- per_team    — флаг на команду
- per_instance — флаг на запуск (хэш от user/team + нонс)

Флаг имеет вид: flag{<comp_slug>_<ch_slug>_<hex>}
"""
import hashlib
import secrets

from ..models_competitions import (
    Competition,
    CompetitionChallenge,
    DynamicFlagStrategy,
)


def generate_dynamic_flag(
    ch: CompetitionChallenge,
    comp: Competition,
    *,
    user_id: int | None,
    team_id: int | None,
    nonce: str | None = None,
) -> str:
    strategy = (
        ch.dynamic_flag_strategy.value
        if hasattr(ch.dynamic_flag_strategy, "value")
        else str(ch.dynamic_flag_strategy)
    )

    if strategy == DynamicFlagStrategy.static.value:
        # Не должны сюда попадать — вызывающий код проверяет.
        raise ValueError("Cannot generate dynamic flag for static strategy")

    if strategy == DynamicFlagStrategy.per_user.value:
        if user_id is None:
            raise ValueError("per_user requires user_id")
        seed = f"u:{user_id}"
    elif strategy == DynamicFlagStrategy.per_team.value:
        if team_id is None:
            raise ValueError("per_team requires team_id")
        seed = f"t:{team_id}"
    elif strategy == DynamicFlagStrategy.per_instance.value:
        seed = f"u:{user_id}:t:{team_id}:n:{nonce or secrets.token_hex(8)}"
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    digest = hashlib.sha256(
        f"{comp.slug}:{ch.slug}:{seed}".encode("utf-8")
    ).hexdigest()[:24]

    return f"flag{{{comp.slug}_{ch.slug}_{digest}}}"