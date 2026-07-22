# ORDO — CTF Training Platform

Платформа для проведения учебных CTF (Capture The Flag) с автоматическим развёртыванием уязвимых контейнеров, проверкой флагов и системой начисления очков.

---

## Содержание

- [Архитектура](#архитектура)
- [Быстрый старт](#быстрый-старт)
- [Структура проекта](#структура-проекта)
- [Конфигурация](#конфигурация)
- [Роли пользователей](#роли-пользователей)
- [API](#api)
- [Добавление заданий](#добавление-заданий)
- [Решения (Write-ups)](#решения-write-ups)
- [Библиотека занятий](#библиотека-занятий)
- [Администрирование](#администрирование)
- [Безопасность](#безопасность)
- [Разработка](#разработка)
- [Устранение неполадок](#устранение-неполадок)

---

## Архитектура

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Пользователь   │────▶│    Nginx    │────▶│   Backend   │
│  (браузер/curl)  │     │   (:80)     │     │  (FastAPI)  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                                │
                       ┌────────────────────────┼────────────────────────┐
                       │                        │                        │
                  ┌────▼────┐              ┌──▼──┐              ┌────▼────┐
                  │   DB    │              │Docker │              │Frontend │
                  │(PostgreSQL)│           │Engine │              │(React)  │
                  └─────────┘              └──┬───┘              └─────────┘
                                              │
                       ┌──────────────────────┼──────────────────────┐
                       │                      │                      │
                  ┌────▼────┐            ┌──▼──┐              ┌────▼────┐
                  │Челлендж 1│            │Челлендж 2│         │Челлендж N│
                  │(изолирован)│          │(изолирован)│       │(изолирован)│
                  └─────────┘            └─────────┘          └─────────┘
```

- **Nginx** — реверс-прокси, маршрутизирует `/api/*` на backend, `/` на frontend
- **Backend** (FastAPI) — API, аутентификация JWT, управление челленджами, пользователями
- **DB** (PostgreSQL) — пользователи, задания, решения, инстансы, write-ups, занятия
- **Docker Engine** — запускает персональные контейнеры челленджей в изолированной сети
- **Frontend** (React + Vite) — UI платформы

---

## Быстрый старт

### Требования

- Docker + Docker Compose
- `docker` доступен без `sudo` (или backend запущен с правами root)
- Для dev-режима: `pnpm` (Node.js 20+)

### Запуск в production

```bash
git clone <repo>
cd ctf-platform
docker compose up -d --build
```

- Платформа: `http://localhost/`
- API docs (Swagger): `http://localhost/api/docs`
- Backend health: `http://localhost:8000/health`

### Дефолтные учётные записи

| Логин | Пароль | Роль |
|-------|--------|------|
| `admin` | `admin123` | admin |
| `moderator` | `moderato123` | moderator |

> ⚠️ Смените пароли перед публичным развёртыванием!

### Dev-режим (frontend + backend)

```bash
# Запускает backend в Docker + frontend dev-сервер
./dev.sh
```

- Frontend dev: `http://localhost:5173`
- Backend API: `http://localhost:8000`

---

## Структура проекта

```
ctf-platform/
├── docker-compose.yml          # оркестрация: db + backend + nginx
├── dev.sh                      # скрипт dev-окружения
├── backend/                    # FastAPI-ядро
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py             # точка входа, роутеры, startup
│       ├── config.py           # настройки (env-переменные)
│       ├── database.py         # SQLAlchemy engine + session
│       ├── models.py           # ORM-модели
│       ├── schemas.py          # Pydantic-схемы
│       ├── security.py         # JWT, bcrypt, guards
│       └── routers/
│           ├── auth.py         # регистрация, вход, /me
│           ├── challenges.py   # список, старт/стоп, проверка флага
│           ├── admin.py        # синхронизация, управление пользователями
│           ├── writeups.py     # CRUD write-ups
│           └── lessons.py      # CRUD библиотеки занятий
│       └── services/
│           ├── challenge_registry.py  # автообнаружение заданий
│           └── orchestrator.py        # Docker: запуск/остановка контейнеров
├── challenges/                 # <-- СЮДА добавляются задания
│   ├── sqli-101/
│   │   ├── manifest.yaml       # метаданные задания
│   │   ├── Dockerfile          # сборка уязвимого приложения
│   │   └── app/
│   │       ├── server.py       # уязвимое приложение
│   │       └── ...
│   ├── xss-101/
│   ├── ssrf-201/
│   └── ...
├── ctf-frontend/               # React + Vite фронтенд
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── api/client.js       # HTTP-клиент к backend
│       ├── api/jwt.js          # декодер JWT на фронте
│       ├── context/AuthContext.jsx
│       ├── components/         # Layout, ChallengeCard, RequireAuth
│       └── pages/              # Login, Challenges, Profile, Admin, ...
├── nginx/
│   └── nginx.conf              # реверс-прокси
└── README.md                   # этот файл
```

---

## Конфигурация

### Переменные окружения (backend)

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `DATABASE_URL` | `postgresql+psycopg2://ctf:ctf@localhost:5432/ctf` | Подключение к PostgreSQL |
| `JWT_SECRET` | `dev_secret_change_me` | Секрет подписи JWT |
| `JWT_ALGORITHM` | `HS256` | Алгоритм JWT |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` (12ч) | Время жизни токена |
| `CHALLENGES_DIR` | `/challenges` | Папка с заданиями |
| `CHALLENGE_PORT_RANGE_START` | `30000` | Начало диапазона портов челленджей |
| `CHALLENGE_PORT_RANGE_END` | `30999` | Конец диапазона |
| `INSTANCE_TTL_SECONDS` | `3600` | TTL инстанса (1 час) |
| `DOCKER_NETWORK` | `ctf-platform_isolated_net` | Docker-сеть для челленджей |
| `PUBLIC_HOST` | `localhost` | Хост для URL инстансов |

### Файл `.env`

```bash
# backend/.env
DATABASE_URL=postgresql+psycopg2://ctf:ctf_password@db:5432/ctf
JWT_SECRET=your-super-secret-key-min-32-chars
PUBLIC_HOST=ctf.example.com
```

---

## Роли пользователей

| Роль | Описание | Доступ |
|------|----------|--------|
| `student` | Обычный участник | Задания, профиль, write-ups (только решённые), библиотека |
| `moderator` | Модератор | Просмотр пользователей, CRUD занятий, просмотр write-ups |
| `admin` | Администратор | Всё + синхронизация заданий, управление пользователями (блокировка, роли, статусы), CRUD write-ups |

---

## API

### Аутентификация

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/auth/register` | Регистрация |
| `POST` | `/auth/login` | Вход (OAuth2 form) |
| `GET` | `/auth/me` | Текущий пользователь |

### Задания

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/challenges` | Список заданий (с флагом `solved`) |
| `POST` | `/challenges/{slug}/start` | Запустить инстанс |
| `POST` | `/challenges/{slug}/stop` | Остановить инстанс |
| `POST` | `/challenges/{slug}/submit` | Проверить флаг |

### Админка

| Метод | Путь | Описание | Роль |
|-------|------|----------|------|
| `POST` | `/admin/challenges/sync` | Синхронизировать задания | admin |
| `POST` | `/admin/instances/reap` | Очистить просроченные | admin |
| `GET` | `/admin/users` | Список пользователей | admin/moderator |
| `PATCH` | `/admin/users/{id}` | Статус / блокировка | admin |
| `PUT` | `/admin/users/{id}/role` | Назначить роль | admin |

### Write-ups

| Метод | Путь | Описание | Роль |
|-------|------|----------|------|
| `GET` | `/writeups` | Список (фильтр по решённым) | авторизован |
| `GET` | `/writeups/{slug}` | Получить решение | авторизован + решено |
| `POST` | `/writeups` | Создать | admin |
| `PUT` | `/writeups/{slug}` | Обновить | admin |
| `DELETE` | `/writeups/{slug}` | Удалить | admin |

### Занятия (библиотека)

| Метод | Путь | Описание | Роль |
|-------|------|----------|------|
| `GET` | `/lessons` | Список | авторизован |
| `GET` | `/lessons/{slug}` | Получить | авторизован |
| `POST` | `/lessons` | Создать | admin/moderator |
| `PUT` | `/lessons/{slug}` | Обновить | admin/moderator |
| `DELETE` | `/lessons/{slug}` | Удалить | admin/moderator |

---

## Добавление заданий

Чтобы добавить новое задание, **не нужно трогать код платформы**.

### 1. Создайте папку

```bash
mkdir challenges/my-new-challenge
cd challenges/my-new-challenge
```

### 2. Напишите `manifest.yaml`

```yaml
title: "SQL Injection 101"
category: "web"
difficulty: "easy"          # easy | medium | hard
points: 100
description: >
  Найди способ обойти форму логина через SQL-инъекцию.
flag: "flag{sql_1nj3ct10n_1s_2asy}"
container_port: 5000        # <-- порт, на котором слушает приложение ВНУТРИ контейнера
```

> ⚠️ **Важно:** `container_port` должен совпадать с портом в `server.py` (`app.run(host="0.0.0.0", port=5000)`). Если не указать — используется **80** по умолчанию, и задание не будет доступно.

### 3. Напишите `Dockerfile`

```dockerfile
FROM python:3.12-slim

RUN useradd -m -u 1001 appuser
WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Флаг в env (или файл) — приложение само читает
ENV FLAG=flag{your_flag_here}

USER appuser
EXPOSE 5000

CMD ["python", "server.py"]
```

### 4. Напишите уязвимое приложение

```python
# app/server.py
from flask import Flask, request
import os

app = Flask(__name__)
FLAG = os.environ.get("FLAG", "flag{default}")

@app.route("/")
def index():
    # намеренно уязвимый код
    return f"Hello, {request.args.get('name', 'guest')}!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)  # <-- обязательно 0.0.0.0
```

### 5. Синхронизируйте

```bash
# Через админку UI или API:
curl -X POST http://localhost/api/admin/challenges/sync   -H "Authorization: Bearer <admin_token>"
```

Задание автоматически появится в списке `/challenges`.

---

## Решения (Write-ups)

Write-up — пошаговое решение задания в формате JSON. Создаётся админом, доступен студенту только после решения задания.

### Формат JSON

```json
{
  "description": "Описание уязвимости",
  "steps": [
    {
      "step": 1,
      "title": "Разведка",
      "detail": "Что заметить в приложении",
      "command": "curl http://target/",
      "screenshot": ""
    },
    {
      "step": 2,
      "title": "Эксплуатация",
      "detail": "Как использовать уязвимость",
      "command": "curl -X POST ...",
      "screenshot": ""
    }
  ],
  "flag": "flag{...}"
}
```

---

## Библиотека занятий

Модераторы и админы могут создавать учебные статьи в Markdown. Доступны всем авторизованным пользователям.

- Slug: `kebab-case` (строчные латинские буквы, цифры, дефисы)
- Поддерживается Markdown: заголовки, списки, код, таблицы, изображения
- Автоматическая транслитерация русского → латиница при генерации slug

---

## Администрирование

### Синхронизация заданий

Выполняется автоматически при старте backend. Ручной запуск:

```bash
curl -X POST http://localhost/api/admin/challenges/sync   -H "Authorization: Bearer <token>"
```

### Очистка просроченных инстансов

```bash
curl -X POST http://localhost/api/admin/instances/reap   -H "Authorization: Bearer <token>"
```

> В production настройте cron или APScheduler для регулярного запуска.

### Управление пользователями

- **Статус** — произвольный текст, отображается как `#статус` в профиле
- **Блокировка** — заблокированный пользователь не может войти и пользоваться API
- **Роль** — `student` / `moderator` / `admin`

> Админ не может заблокировать себя или другого админа.

---

## Безопасность

### Изоляция челленджей

Каждый челлендж запускается в отдельном Docker-контейнере:

- **Отдельная сеть** `isolated_net` — без доступа к `platform_net` (backend + DB)
- **cap_drop=ALL** + **no-new-privileges**
- **Лимиты**: 256MB RAM, 0.5 CPU
- **TTL**: автоматическое удаление по истечении времени
- **Автоостановка**: контейнер останавливается после верного флага

### Рекомендации для production

1. **HTTPS** — замените `PUBLIC_HOST` на домен с SSL
2. **CORS** — ограничьте `allow_origins` в `main.py` конкретным доменом фронтенда
3. **Rate limiting** — добавьте лимиты на `/auth/login` и `/challenges/*/submit`
4. **Docker socket** — используйте `docker-socket-proxy` с ограниченными правами вместо прямого монтирования `/var/run/docker.sock`
5. **Secrets** — храните `JWT_SECRET` и пароли БД в Docker Secrets или Vault
6. **isolated_net internal** — если челленджам не нужен исходящий интернет, добавьте `internal: true` в `docker-compose.yml`

---

## Разработка

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd ctf-frontend
pnpm install
pnpm dev
```

### Тесты

```bash
# Backend (pytest)
cd backend
pytest

# Frontend lint
pnpm lint
```

---

## Устранение неполадок

### Челлендж запустился, но не отвечает

1. Проверьте `container_port` в `manifest.yaml` — должен совпадать с портом в `server.py`
2. Проверьте, что приложение слушает на `0.0.0.0`, не на `127.0.0.1`
3. Проверьте `docker ps` — порт опубликован?
4. Проверьте `docker logs <container-id>` — приложение стартовало?

### Tomcat (metasploit-201) не работает

```bash
# Проверьте, что webapps — папка, не файл
docker exec <id> ls -la /usr/local/tomcat/
# Если webapps — файл, исправьте Dockerfile: добавьте mkdir -p
```

### CORS-ошибки

Проверьте `allow_origins` в `backend/app/main.py` и `VITE_API_URL` во фронтенде.

### База данных не поднимается

```bash
docker compose logs db
# Проверьте healthcheck: pg_isready -U ctf -d ctf
```

---

## Лицензия

MIT License — учебный проект. Используйте только в контролируемой среде.

---

## Авторы

CTF Training Platform — проект для обучения информационной безопасности.
