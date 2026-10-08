"""Docker-сеть под соревнование.

Сеть создаётся при публикации (draft -> announced), удаляется при
финальном удалении соревнования. Имя: ctf-comp-{slug}_net.
Использует тот же docker-клиент, что orchestrator.
"""
import docker
from docker.errors import APIError, NotFound

from ..models_competitions import Competition


_client = docker.from_env()


def network_name(slug: str) -> str:
    return f"ctf-comp-{slug}_net"


def ensure_network(competition: Competition) -> str:
    name = network_name(competition.slug)
    try:
        _client.networks.get(name)
        return name
    except NotFound:
        pass

    # isolated = True по умолчанию, allow_internet — снимает internal
    cfg = competition.network_config or {}
    internal = bool(cfg.get("isolated", True)) and not bool(cfg.get("allow_internet", False))

    try:
        _client.networks.create(
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
    try:
        net = _client.networks.get(network_name(slug))
    except NotFound:
        return
    try:
        net.remove()
    except APIError:
        # Сеть занята контейнерами — не валим операцию.
        pass