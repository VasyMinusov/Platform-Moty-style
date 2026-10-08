FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

COPY app ./app

# Папка для заданий соревнований (мапится volume'ом в docker-compose.yml).
RUN mkdir -p /challenges/competitions

# Проверка, что все модули сервисов импортируются без ошибок.
# Docker-клиент создаётся лениво, поэтому сокет на build-этапе не нужен.
RUN python -c "import app.services.competition_audit, \
app.services.competition_network, \
app.services.competition_ports, \
app.services.competition_service, \
app.services.competition_team_service, \
app.services.competition_challenge_service, \
app.services.competition_manifest"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]