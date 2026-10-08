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
    client = _get_client()
    name = network_name(competition.slug)
    try:
        client.networks.get(name)
        return name
    except NotFound:
        pass

    cfg = competition.network_config or {}
    internal = bool(cfg.get("isolated", True)) and not bool(cfg.get("allow_internet", False))

    try:
        client.networks.create(
            name,
            driver="bridge",
            internal=internal,
            labels={"ctf-competition": competition.slug},
        )
    except APIError as e:
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