FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Alembic-инфраструктура должна лежать рядом с app/, чтобы main.py
# мог найти alembic.ini и папку alembic/ по абсолютному пути от /app.
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]