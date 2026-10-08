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

# Проверка импортов. Docker-клиент создаётся лениво, поэтому сокет на
# build-этапе не нужен.
RUN python -c "import app.services.competition_audit, \
app.services.competition_network, \
app.services.competition_ports, \
app.services.competition_service, \
app.services.competition_team_service, \
app.services.competition_challenge_service, \
app.services.competition_manifest, \
app.services.competition_build_security, \
app.services.competition_dynamic_flags, \
app.services.competition_instance_service, \
app.services.competition_leaderboard_service, \
app.services.competition_dashboard_service, \
app.services.competition_appeal_service, \
app.services.competition_scoring_service, \
app.services.competition_stream, \
app.services.notification_service, \
app.models_notifications, \
app.schemas_notifications, \
app.routers.notifications"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]