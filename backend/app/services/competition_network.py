"""Docker-сеть под соревнование.

Сеть создаётся при публикации (draft -> announced), удаляется при
финальном удалении соревнования. Имя: ctf-comp-{slug}_net.

Docker-клиент создаётся лениво: на этапе сборки образа backend сокет
недоступен, а импорт модуля не должен падать.
"""
from typing import Optional

import docker
from docker.errors import APIError, NotFound

from ..models_competitions import Competition


_docker_client = None


def _get_client():
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


def network_name(slug: str) -> str:
    return f"ctf-comp-{slug}_net"


def ensure_network(competition: Competition) -> str:
    """Гарантирует, что сеть соревнования существует. Возвращает имя.

    FIX: сеть НИКОГДА не создаётся с флагом internal=true.

    Раньше здесь было:
        internal = bool(cfg.get("isolated", True)) and not bool(cfg.get("allow_internet", False))
        client.networks.create(..., internal=internal, ...)

    Значение по умолчанию для `network_config.isolated` — True, поэтому
    все соревновательные сети создавались internal=true. В Docker это
    не просто «изолированный bridge», это «полный запрет внешнего
    трафика и блокировка публикации портов»: `docker run -p 30001:5060`
    не создаёт NAT-правило, `docker ps` показывает только `5060/tcp`
    без `->`, и curl с хоста получает "connection refused".

    Для CTF это фатально: студент не может открыть URL инстанса по
    опубликованному порту.

    Изоляция от platform_net (backend + db) обеспечивается тем, что
    это отдельная bridge-сеть — задания по-прежнему не видят backend
    и базу. Флаг internal нам для этого не нужен.
    """
    client = _get_client()
    name = network_name(competition.slug)

    try:
        client.networks.get(name)
        return name
    except NotFound:
        pass

    try:
        client.networks.create(
            name,
            driver="bridge",
            internal=False,
            labels={"ctf-competition": competition.slug},
        )
    except APIError as e:
        # Гонка: параллельный старт инстансов. Сеть уже создана кем-то
        # другим — просто вернём имя.
        if "already exists" in str(e).lower():
            return name
        raise
    return name


def remove_network(slug: str) -> None:
    client = _get_client()
    try:
        net = client.networks.get(network_name(slug))
    except NotFound:
        return
    try:
        net.remove()
    except APIError:
        pass