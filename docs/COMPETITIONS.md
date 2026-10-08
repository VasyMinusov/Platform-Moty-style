# Модуль «Соревнования»

Полный справочник по модулю: модели, API, роли, жизненный цикл, scoring,
безопасность.

## Содержание

- [Обзор](#обзор)
- [Роли и права](#роли-и-права)
- [Жизненный цикл соревнования](#жизненный-цикл-соревнования)
- [Заявки](#заявки)
- [Команды](#команды)
- [Задания соревнования](#задания-соревнования)
- [Формат ZIP](#формат-zip)
- [Инстансы](#инстансы)
- [Scoring](#scoring)
- [Leaderboard](#leaderboard)
- [Апелляции](#апелляции)
- [Уведомления](#уведомления)
- [WebSocket](#websocket)
- [Аудит](#аудит)
- [Безопасность](#безопасность)
- [API-справочник](#api-справочник)

---

## Обзор

Модуль соревнований — отдельный слой поверх существующей платформы.
Не пересекается с глобальными `Challenge`, `Solve`, `ChallengeInstance`,
кроме общих таблиц `users` и опционального промоушена заданий.

Ключевые сущности:

- `Competition` — соревнование (slug, расписание, режим, scoring).
- `CompetitionModerator` — привязка модератора к соревнованию.
- `CompetitionApplication` — заявка пользователя или команды.
- `CompetitionTeam`, `CompetitionTeamMember` — команды.
- `CompetitionChallenge` — задание внутри соревнования.
- `CompetitionChallengeFile` — файлы задания (static).
- `CompetitionSolve` — решения.
- `CompetitionScoreEvent` — история изменения очков.
- `CompetitionAppeal` — апелляции.
- `CompetitionAuditLog` — журнал действий.
- `Notification` — in-app уведомления.

---

## Роли и права

| Действие | admin | moderator | student |
|---|---|---|---|
| Создать соревнование | + | + (черновик) | — |
| Публиковать (draft → announced) | + | — | — |
| Открыть/закрыть регистрацию | + | + | — |
| Запустить/пауза/финиш | + | + | — |
| Назначать модераторов | + | — | — |
| Загружать ZIP-задания | + | + | — |
| Видеть флаги | + | — | — |
| Промоушен заданий в глобальные | + | — | — |
| Одобрять заявки | + | + | — |
| Смотреть заявки | + | + | — |
| Ручная корректировка очков | + | + | — |
| Решать апелляции | + | + | — |
| Подавать заявку | — | — | + |
| Создавать команду | — | — | + |
| Запускать инстанс | — | — | + (после одобрения) |
| Submit флага | — | — | + (после одобрения) |

Модератор видит и управляет только теми соревнованиями, в которых он
назначен `responsible` или `helper`. Исключение: пока соревнование в
статусе `draft`, его создатель-модератор имеет доступ, даже если ещё
не был назначен формально.

---

## Жизненный цикл соревнования

```
draft
  | publish (admin)
  v
announced
  | open-registration
  v
registration_open
  | close-registration
  v
registration_closed
  | start
  v
running <---- resume ----+
  | pause                |
  v                      |
paused ------------------+
  | finish
  v
finished
```

Побочные эффекты переходов:

- `draft → announced`: выделяется диапазон портов, создаётся Docker-сеть.
- `running`, `paused`, `finished`, `cancelled`: показываются задания с
  `visibility=visible_after_start`.
- `finished`, `cancelled`: останавливаются все инстансы соревнования.

Отменить соревнование можно из любого статуса, кроме `finished`.

---

## Заявки

Режимы:

- **individual**: пользователь подаёт заявку на себя.
- **team**: заявка идёт от имени команды (создаётся капитаном).
- **both**: и то, и другое.

Статусы заявки:

- `pending` — ожидает решения.
- `approved` — одобрена, участие разрешено.
- `rejected` — отклонена.
- `withdrawn` — отозвана пользователем.
- `waitlist` — в листе ожидания.
- `team_pending` — командная заявка, ещё не набран min_team_size.
- `team_rejected` — командная заявка, отклонена.

Правила:

- Один пользователь — не более одной активной заявки (индивидуальной
  или через команду) в рамках соревнования.
- Отзыв (`withdraw`) разрешён в статусах `pending`, `waitlist`,
  `team_pending`.
- После `registration_closes_at` новые заявки принимаются только если
  `allow_late_application=true`.
- Лимит `max_participants` проверяется при подаче.
- Модератор/админ может отклонять и переносить в лист ожидания с
  комментарием.

---

## Команды

- Создаёт пользователь → он становится капитаном.
- Приглашения: по username или по invite-коду.
- Капитан подтверждает кик; капитан не может покинуть команду — только
  распустить или передать (передача капитана не реализована в MVP).
- Один пользователь — только в одной команде в рамках соревнования.
- Команда автоматически становится `pending`, когда набран `min_team_size`.
- Пока команда в `forming`, заявка в статусе `team_pending`, участие
  запрещено.
- Команды видны всем участникам, если `public_team_roster=true`, иначе —
  только капитану и приглашённым.

---

## Задания соревнования

Отдельные от глобальных. Не шарятся между соревнованиями, но могут быть
промоутнуты в глобальные после завершения.

Типы (`kind`):

- `docker` — образ собирается из ZIP, запускается контейнер.
- `static` — файлы раздаются через API (OSINT, stego, forensics).

Категории (`type`): `web`, `pwn`, `crypto`, `stego`, `osint`, `forensics`,
`reversing`, `misc`, `pentest`, `network`, `hardware`, `other`.

Стратегии флагов:

- `static` — из манифеста.
- `per_user` — генерируется на пользователя.
- `per_team` — генерируется на команду.
- `per_instance` — генерируется на каждый запуск контейнера.

Подсказки:

- Массив `{text, cost}` в `hints_json`.
- Покупка один раз на пользователя/команду.
- Стоимость списывается как `hint_penalty`.

Зависимости:

- Массив slug'ов в `dependencies_json`.
- Все должны существовать в этом соревновании.
- Самозависимость запрещена.
- Не решённые зависимости не дают запустить инстанс.

Видимость:

- `hidden` — не видно никому, кроме админа.
- `visible_after_start` — видно после `start` соревнования.
- `visible` — видно всегда.

---

## Формат ZIP

Один ZIP = одно задание. Структура:

```
my-challenge.zip
|-- manifest.yaml
|-- Dockerfile             (для kind=docker)
|-- app/                   (для kind=docker)
|   `-- ...
`-- public/                (для kind=static)
    `-- ...
```

### manifest.yaml

```yaml
title: "SQL Injection 101"
type: "web"                # web | pwn | crypto | stego | osint | ...
kind: "docker"             # docker | static
category: "web"
difficulty: "easy"         # easy | medium | hard | insane
description: >
  Найди способ обойти форму логина.
points: 100
flag: "flag{sql_1nj3ct10n_1s_2asy}"
container_port: 5000       # обязательно для docker, запрещено для static
dynamic_flag_strategy: "static"    # static | per_user | per_team | per_instance
visibility: "visible_after_start"  # hidden | visible_after_start | visible
hints:
  - text: "Попробуй кавычку"
    cost: 10
dependencies: []
metadata:
  docker:
    dockerfile_path: "Dockerfile"
    env: {}
```

### Валидация ZIP

При загрузке проверяется:

- Размер ≤ `competition_zip_max_bytes`.
- Количество файлов ≤ `competition_zip_max_files`.
- Нет `..`, абсолютных путей, symlink, `__MACOSX`, `Thumbs.db`.
- `manifest.yaml` в корне.
- Обязательные поля манифеста.
- `metadata` соответствует `type` (через Pydantic).
- `container_port` не в `RESERVED_PORTS`.
- `container_port` не конфликтует с другими заданиями соревнования.
- `Dockerfile` не содержит запрещённых инструкций
  (`--privileged`, `--network=host`, `mount=type=bind`, доступ к
  `/var/run/docker.sock` и т.д.).
- Базовый образ из allowlist (`settings.build_enforce_base_image_allowlist`).
- Зависимости существуют в соревновании.
- Для `kind=static` — непустая папка `public/`.

---

## Инстансы

- Ключ: `(competition_id, challenge_id, user_id)` или
  `(competition_id, challenge_id, team_id)`.
- Сеть: `ctf-comp-{slug}_net`, `internal: true` если `network_config.isolated`.
- Порты: из `port_range_start/end` соревнования (выделяется при `publish`).
- TTL: `instance_ttl_seconds` соревнования.
- Лимиты: `max_instances_per_user`, `max_instances_per_team`,
  `max_instances_per_competition`.
- Автостоп: после верного флага, по TTL, при `finish` соревнования.
- Динамический флаг передаётся через `FLAG` и `CTF_FLAG`.

---

## Scoring

Три режима (`scoring_config.mode`):

### `fixed`

Все получают одинаковые очки (`default_points` или `ch.points`).

### `dynamic_decay`

Первое решение `max_points`, дальше по формуле:

- `step`: `points = max(min_points, max_points - floor(rank / decay_interval) * decay_step)`
- `linear`: линейное убывание до `min_points`
- `logarithmic`: `points = max(min_points, max_points - log2(rank) * decay_step)`

`compute_at`:

- `on_solve` — фиксируется при решении.
- `dynamic` — пересчитывается (в MVP не реализовано, всегда `on_solve`).

### `placement`

Очки раздаются при `finish` по местам. Параметры в
`scoring_config.placement.places`:

```json
{
  "places": [
    {"place": 1, "points": 1500},
    {"place": 2, "points": 1000},
    {"place": 3, "points": 700}
  ],
  "default_points": 100
}
```

### Штрафы и бонусы

- **Штраф** — за подсказку, `hint_penalty`.
- **Бонусы** — `first_blood`, `all_category`, `custom`.

### Tie-breaker

- `last_solve_time` — у кого последнее решение раньше.
- `first_solve_time` — у кого первое решение раньше.
- `solves_count` — у кого больше решённых.
- `alphabetic` — по алфавиту.

### Ручная корректировка

`POST /admin/competitions/{slug}/score-adjust` создаёт
`CompetitionScoreEvent` с `reason=manual`. Пишется в аудит.

---

## Leaderboard

`GET /competitions/{slug}/leaderboard` — снапшот с ранжированием.

- Dense ranking: одинаковые очки → одинаковое место.
- Для team-режима ранжируются команды, для individual — пользователи,
  для both — оба списка.
- Видимость: `public`, `participants`, `hidden` (в конструкторе).
- Экспорт CSV: `GET /competitions/{slug}/leaderboard/export` (только
  админ/модератор).

Обновление в реальном времени — через WebSocket
`/competitions/{slug}/stream`.

---

## Апелляции

- Подать: `POST /competitions/{slug}/appeals`.
- Только одна открытая на пользователя/задание.
- Смотреть свои: `GET /competitions/{slug}/my-appeals`.
- Модератор: `GET /admin/competitions/{slug}/appeals` и
  `PATCH /admin/competitions/{slug}/appeals/{id}` со `status` в
  `accepted` / `rejected`.
- Уведомление автору.

---

## Уведомления

In-app, хранятся в БД, доставляются через WebSocket
`/notifications/stream`.

Типы:

- `application.approved` / `application.rejected` / `application.waitlist`
- `team.invite` / `team.invite.accepted` / `team.joined`
- `appeal.created` / `appeal.accepted` / `appeal.rejected`
- `notification.created` (транспортное событие WS)

API:

- `GET /notifications` — список с пагинацией.
- `GET /notifications/unread-count`.
- `POST /notifications/{id}/read`.
- `POST /notifications/read-all`.
- `DELETE /notifications/{id}`.
- `DELETE /notifications`.

Хранение: БД (`notifications`). Лимит истории — 50 последних на
пользователя (в UI); в БД хранятся все.

---

## WebSocket

Два канала, один хаб:

- `/competitions/{slug}/stream` — событие `leaderboard.snapshot`,
  `solve.created`.
- `/notifications/stream` — событие `notifications.hello`,
  `notification.created`.

Аутентификация — токен в query-параметре `?token=...`.

При отсутствии токена/неавторизованного пользователя соединение
закрывается кодом 1008.

---

## Аудит

`competition_audit_log`:

- `action` — код действия (`competition.create`, `challenge.upload`,
  `score.manual_adjust`, `appeal.accepted` и т.п.).
- `actor_id`, `target_type`, `target_id`, `payload_json`.

Просмотр: `GET /admin/competitions/{slug}/audit?limit=100`.

---

## Безопасность

- Отдельная Docker-сеть на соревнование, `internal: true` по умолчанию.
- Лимиты на контейнер: 256 MB RAM, 0.5 CPU, `pids_limit=128`,
  `cap_drop=ALL`.
- Сборка без сети (`network_mode=none`) + проверка Dockerfile +
  allowlist базовых образов.
- Rate limiting на ключевые endpoints.
- Флаги хранятся только в виде SHA-256.
- Динамические флаги генерируются per-user/team/instance.
- Аномалии (fast_solve, hint_only) подсвечиваются в дашборде.

---

## API-справочник

Полный список endpoint'ов см. в автоматически сгенерированной
документации Swagger: `http://<host>/api/docs`.

Группы тегов:

- `competitions` — публичные/участнические.
- `competitions:admin` — админские.
- `competitions:teams` — команды.
- `competitions:challenges` — задания.
- `competitions:instances` — инстансы и submit.
- `competitions:leaderboard` — лидерборд.
- `competitions:dashboard` — дашборд и корректировка очков.
- `competitions:appeals` — апелляции.
- `competitions:ws` — WebSocket.
- `notifications` — уведомления.