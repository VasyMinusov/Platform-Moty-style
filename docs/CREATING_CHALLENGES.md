# Создание заданий для соревнований

Руководство по подготовке заданий для всех направлений: web, crypto,
reverse, forensics, stego, pwn, osint, misc. Один ZIP = одно задание.

## Содержание

- [Общие принципы](#общие-принципы)
- [Структура ZIP](#структура-zip)
- [Общие поля manifest.yaml](#общие-поля-manifestyaml)
- [Типы заданий](#типы-заданий)
  - [web](#web)
  - [crypto](#crypto)
  - [reverse](#reverse)
  - [forensics](#forensics)
  - [stego](#stego)
  - [pwn](#pwn)
  - [osint](#osint)
  - [misc](#misc)
- [Динамические флаги](#динамические-флаги)
- [Подсказки и зависимости](#подсказки-и-зависимости)
- [Валидация и частые ошибки](#валидация-и-частые-ошибки)
- [Чек-лист перед загрузкой](#чек-лист-перед-загрузкой)

---

## Общие принципы

1. **Один ZIP — одно задание.** Не пакуйте несколько заданий в один архив.
2. **Два вида заданий**:
   - `kind: docker` — образ собирается из `Dockerfile`, запускается
     контейнер, порт публикуется. Для web, pwn, pentest, network.
   - `kind: static` — файлы раздаются студенту через API. Для crypto,
     stego, osint, forensics, reverse, misc.
3. **`manifest.yaml` обязателен** и лежит в корне ZIP.
4. **Все slug'и** — kebab-case, только латиница, цифры, дефис.
5. **Флаги** хранятся только в виде SHA-256. В `manifest.yaml` можно
   указать `flag` (открытый текст) или `flag_hash` (если не хотите
   хранить plaintext).
6. **Документация внутри задания** — описание пишется в `description`,
   оно видно студенту. Секретные детали там не оставляйте.

---

## Структура ZIP

### Docker-задание (web, pwn, pentest, network)

```
my-challenge.zip
├── manifest.yaml
├── Dockerfile
└── app/
    ├── server.py
    ├── requirements.txt
    └── ...
```

### Static-задание (crypto, stego, osint, forensics, reverse, misc)

```
my-challenge.zip
├── manifest.yaml
└── public/
    ├── image.png
    ├── ciphertext.bin
    └── ...
```

Всё содержимое `public/` раздаётся студенту. `manifest.yaml` и
`Dockerfile` не раздаются.

### Оба вида вместе (например, pwn с бинарём в static-виде)

Если задание — не Docker, но с бинарём (reverse), кладите бинарь в
`public/`:

```
my-rev.zip
├── manifest.yaml
└── public/
    ├── challenge
    └── README.txt
```

---

## Общие поля manifest.yaml

```yaml
title: "Название задания"          # обязательно
type: "web"                        # обязательно, см. список ниже
kind: "docker"                     # обязательно: docker | static
category: "web"                    # свободное поле, обычно совпадает с type
difficulty: "easy"                 # easy | medium | hard | insane
description: >
  Что студент видит при открытии задания. Опишите легенду и цель.
points: 100                        # базовые очки (переопределяется scoring соревнования)
flag: "flag{...}"                  # открытый флаг (взаимоисключим с flag_hash)
# flag_hash: "..."                 # SHA-256 флага, если не хотите хранить plaintext
container_port: 5000               # обязательно для kind=docker, запрещено для static
dynamic_flag_strategy: "static"    # static | per_user | per_team | per_instance
visibility: "visible_after_start"  # hidden | visible_after_start | visible
hints:
  - text: "Попробуйте кавычку"
    cost: 10
dependencies: []                   # массив slug'ов заданий, которые надо решить раньше
metadata: {}                       # схема зависит от type, см. ниже
```

Типы (`type`): `web`, `pwn`, `crypto`, `stego`, `osint`, `forensics`,
`reversing`, `misc`, `pentest`, `network`, `hardware`, `other`.

В `metadata` валидация строгая — неизвестные поля игнорируются, но
обязательные проверяются. Схемы по типам — ниже.

---

## Типы заданий

### web

**kind**: `docker`

Web-приложение с уязвимостью. Студент подключается к опубликованному
порту и эксплуатирует.

**metadata**:

```yaml
metadata:
  docker:
    dockerfile_path: "Dockerfile"   # опционально, default "Dockerfile"
    build_args: {}                  # опционально
    env: {}                         # переменные окружения контейнера
    healthcheck_path: "/"           # опционально
```

**Dockerfile**:

```dockerfile
FROM python:3.12-slim

RUN useradd -m -u 1001 appuser
WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

USER appuser
EXPOSE 5000

CMD ["python", "server.py"]
```

**`app/server.py`** (пример):

```python
from flask import Flask, request
import os

app = Flask(__name__)
FLAG = os.environ.get("FLAG", "flag{default}")

@app.route("/")
def index():
    return f"Hello, {request.args.get('name', 'guest')}!"

if __name__ == "__main__":
    # Обязательно host="0.0.0.0", иначе контейнер не будет доступен.
    app.run(host="0.0.0.0", port=5000)
```

**Важно**:
- Приложение обязано слушать `0.0.0.0`, а не `127.0.0.1`.
- `container_port` должен совпадать с портом в `server.py`.
- Базовый образ из allowlist: `python:3.12-slim`, `node:20-alpine`,
  `nginx:alpine`, `alpine:3.20`, `ubuntu:22.04`, `debian:bookworm-slim`.
- В Dockerfile запрещены: `--privileged`, `--network=host`,
  `--pid=host`, `mount=type=bind`, доступ к `/var/run/docker.sock`,
  `ADD http://...`, `COPY --from=...`, `VOLUME /...`.

**Флаг в контейнере**:
- Статический: `ENV FLAG=flag{...}` в Dockerfile, или `flag` в манифесте,
  контейнер не получает env от оркестратора.
- Динамический (`per_user`/`per_team`/`per_instance`): оркестратор
  передаёт `FLAG` и `CTF_FLAG` в `environment`, приложение должно
  читать `os.environ["FLAG"]` и отдавать его при эксплуатации.

---

### crypto

**kind**: `static`

Классическая криптография. Студент получает файлы (шифротекст, публичный
ключ, параметры) и расшифровывает флаг.

**metadata**:

```yaml
metadata:
  cipher_type: "AES-CBC"           # опционально, свободный текст
  files: ["ciphertext.bin", "public.pem"]
  description_extra: "AES-128-CBC, ключ неизвестен"
```

**Структура**:

```
crypto-challenge.zip
├── manifest.yaml
└── public/
    ├── ciphertext.bin
    ├── public.pem
    └── encrypted_flag.txt
```

**Пример manifest.yaml**:

```yaml
title: "RSA Small Exponent"
type: "crypto"
kind: "static"
category: "crypto"
difficulty: "medium"
description: >
  Мы перехватили зашифрованное сообщение. Публичный ключ прилагается.
  Что-то подсказывает, что экспонента слишком мала.
points: 200
flag: "flag{sm4ll_exp0n3nt_att4ck}"
visibility: "visible_after_start"
metadata:
  cipher_type: "RSA"
  files: ["public.pem", "ciphertext.hex"]
```

**Совет**: флаг в статическом crypto обычно не в файле, а получается
после расшифровки. Позаботьтесь, чтобы студент точно понял, какой формат
флага ожидается (например, в описании скажите «флаг имеет формат
flag{...}»).

---

### reverse

**kind**: `static`

Реверс-инжиниринг. Студент получает бинарь, анализирует его, находит
флаг или логику проверки.

**metadata** (используется схема `PwnMeta`):

```yaml
metadata:
  has_source: false                # true, если приложен исходник
  has_binary: true
  download_path: "/challenge"      # опционально, для описания
  has_libc: false                  # true, если приложен libc
```

**Структура**:

```
reverse-challenge.zip
├── manifest.yaml
└── public/
    ├── challenge
    └── libc.so.6                  # опционально
```

**Пример manifest.yaml**:

```yaml
title: "Simple Checker"
type: "reversing"
kind: "static"
category: "reverse"
difficulty: "easy"
description: >
  Бинарь просит пароль и проверяет его. Найдите правильный пароль —
  он и есть флаг (формат flag{...}).
points: 150
flag: "flag{r3v3rs1ng_1s_fun}"
visibility: "visible_after_start"
metadata:
  has_source: false
  has_binary: true
  has_libc: false
```

**Важно**: бинарь должен запускаться в окружении студента. Если он
собран под конкретный libc — приложите libc и ld.so или соберите
статически (`gcc -static`).

---

### forensics

**kind**: `static`

Форензика: PCAP, дамп памяти, образ диска, логи. Студент извлекает из
артефакта флаг.

**metadata**:

```yaml
metadata:
  artifact_type: "pcap"            # pcap | memory_dump | disk_image | log | other
  files: ["capture.pcap"]
```

**Структура**:

```
forensics-challenge.zip
├── manifest.yaml
└── public/
    └── capture.pcap
```

**Пример manifest.yaml**:

```yaml
title: "Suspicious Traffic"
type: "forensics"
kind: "static"
category: "forensics"
difficulty: "medium"
description: >
  Админ заметил подозрительный трафик. Дамп прилагается.
  Найдите, что передавалось в открытом виде.
points: 200
flag: "flag{pl41nt3xt_cr3d3nt14ls}"
visibility: "visible_after_start"
metadata:
  artifact_type: "pcap"
  files: ["capture.pcap"]
```

**Совет**: PCAP удобно генерировать скриптом (например, через scapy) —
тогда флаг легко менять при ротации. См. пример в
`challenges/pcap-201/app/build_pcap.py`.

---

### stego

**kind**: `static`

Стеганография: флаг спрятан в картинке, аудио, видео, архиве.

**metadata**:

```yaml
metadata:
  media_type: "image"              # image | audio | video | archive | other
  files: ["image.png"]
  hint_about_tool: "zsteg, binwalk"   # опционально
```

**Структура**:

```
stego-challenge.zip
├── manifest.yaml
└── public/
    └── image.png
```

**Пример manifest.yaml**:

```yaml
title: "Hidden in Plain Sight"
type: "stego"
kind: "static"
category: "stego"
difficulty: "easy"
description: >
  Картинка кажется обычной, но что-то в ней спрятано.
points: 100
flag: "flag{lsb_st3g0_1s_e4sy}"
visibility: "visible_after_start"
metadata:
  media_type: "image"
  files: ["image.png"]
  hint_about_tool: "zsteg / stegsolve / exiftool"
```

**Проверьте**:
- Флаг не виден при открытии файла в просмотрщике.
- EXIF не содержит флаг в открытом виде (или содержит, если это
  задумано — тогда `difficulty: easy`).
- Инструменты из подсказки действительно находят флаг.

---

### pwn

**kind**: `static` или `docker`

**Static-вариант**: бинарь запускается студентом локально, эксплойт
отправляется через submit.

**Docker-вариант**: бинарь слушает порт, студент подключается `nc` и
эксплуатирует.

#### Static-вариант

**metadata** (схема `PwnMeta`):

```yaml
metadata:
  has_source: false
  has_binary: true
  has_libc: true
  download_path: "/challenge"
```

**Структура**:

```
pwn-static.zip
├── manifest.yaml
└── public/
    ├── challenge
    ├── libc.so.6
    └── ld-linux-x86-64.so.2
```

#### Docker-вариант

**metadata**:

```yaml
metadata:
  docker:
    dockerfile_path: "Dockerfile"
    healthcheck_path: null
  has_source: false
  has_binary: true
  has_libc: false
  download_path: "/challenge"
```

**Dockerfile**:

```dockerfile
FROM ubuntu:22.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends socat \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1001 appuser
WORKDIR /app

COPY app/challenge .
COPY app/flag.txt /flag.txt
RUN chmod +x challenge && chmod 644 /flag.txt

USER appuser
EXPOSE 5000

CMD ["socat", "TCP-LISTEN:5000,reuseaddr,fork", "EXEC:./challenge"]
```

**Структура**:

```
pwn-docker.zip
├── manifest.yaml
├── Dockerfile
└── app/
    ├── challenge
    └── flag.txt
```

**Пример manifest.yaml**:

```yaml
title: "Basic Overflow"
type: "pwn"
kind: "docker"
category: "pwn"
difficulty: "medium"
description: >
  Простой бинарь с переполнением буфера. Внутри есть функция win().
  Подключитесь по nc и получите shell.
points: 250
flag: "flag{buff3r_0v3rfl0w_101}"
container_port: 5000
visibility: "visible_after_start"
metadata:
  docker: {}
  has_source: false
  has_binary: true
  has_libc: false
```

**Важно**:
- Для pwn-контейнера нужен `socat` (или `xinetd`), чтобы обрабатывать
  несколько подключений.
- Бинарь должен быть собран под тот же libc, что в контейнере.
- Если нужен ASLR-bypass через утечку — позаботьтесь, чтобы ASLR был
  включён (по умолчанию в Docker так и есть).

---

### osint

**kind**: `static`

OSINT-задание: студент по вводным данным находит информацию в открытых
источниках (соцсети, домены, реестры, кэш поисковиков).

**metadata**:

```yaml
metadata:
  target_type: "person"            # person | company | domain | image | other
  starting_material: ["photo.jpg", "brief.txt"]
  external_links: ["https://example.com/start"]
```

**Структура**:

```
osint-challenge.zip
├── manifest.yaml
└── public/
    ├── brief.txt
    └── photo.jpg
```

**Пример manifest.yaml**:

```yaml
title: "Find the Founder"
type: "osint"
kind: "static"
category: "osint"
difficulty: "medium"
description: >
  Мы знаем только фото основателя компании. Найдите его полное имя
  и город, где он родился. Флаг — flag{имя_город} в нижнем регистре,
  без пробелов.
points: 200
flag: "flag{ivan_petrov_moscow}"
visibility: "visible_after_start"
metadata:
  target_type: "person"
  starting_material: ["photo.jpg"]
  external_links: []
```

**Важно**:
- Не используйте реальные данные без согласия.
- Все ссылки на внешние источники должны быть стабильны (архив
  веб-страницы, если сайт может исчезнуть).
- Формат флага опишите явно (регистр, разделители), иначе студенты
  будут писать правильный ответ в неверном формате.

---

### misc

**kind**: `static`

Всё, что не влезло в другие категории: логические задачи, кодировки,
нестандартные форматы.

**metadata**:

```yaml
metadata:
  files: ["puzzle.txt"]
  description_extra: "Base64 + ROT13"
```

**Структура**:

```
misc-challenge.zip
├── manifest.yaml
└── public/
    └── puzzle.txt
```

**Пример manifest.yaml**:

```yaml
title: "Double Encoding"
type: "misc"
kind: "static"
category: "misc"
difficulty: "easy"
description: >
  Файл закодирован дважды. Первый слой — Base64, второй — ROT13.
points: 50
flag: "flag{lay3rs_4r3_fun}"
visibility: "visible_after_start"
metadata:
  files: ["puzzle.txt"]
```

---

## Динамические флаги

Если задание предполагает, что студенты могут обмениваться флагами
(например, pwn-эксплойт публикуют в чате), используйте динамические
флаги.

`dynamic_flag_strategy` в манифесте:

- `static` — флаг из манифеста.
- `per_user` — флаг генерируется на каждого пользователя.
- `per_team` — флаг генерируется на команду.
- `per_instance` — флаг генерируется при каждом запуске контейнера.

Для `kind=docker` оркестратор передаёт флаг в контейнер через
переменные окружения `FLAG` и `CTF_FLAG`. Приложение должно их
прочитать:

```python
import os
FLAG = os.environ.get("FLAG", "flag{static_default}")
```

Для `kind=static` динамические флаги не имеют смысла (нет инстанса,
который бы их получил) — используйте `static`.

Формат сгенерированного флага:

```
flag{<comp_slug>_<ch_slug>_<24-hex>}
```

Пример: `flag{demo-2026_web-sqli_a3f5b2c1d4e6f7a8b9c0d1e2}`.

---

## Подсказки и зависимости

### Подсказки

```yaml
hints:
  - text: "Стоимость подсказки списывается как штраф"
    cost: 10
  - text: "Флаг в переменной окружения"
    cost: 25
```

Подсказки покупаются один раз на пользователя или на команду.
Стоимость списывается как `hint_penalty`. Если стоимость 0 — подсказка
бесплатная.

### Зависимости

```yaml
dependencies: ["sql-injection-101", "auth-bypass"]
```

Все slug'и должны существовать в этом же соревновании. Студент не
сможет запустить инстанс задания, пока не решил все зависимости.
Самозависимость запрещена (валидация вернёт 400).

Полезно для сюжетных соревнований: «сначала получи доступ к панели,
потом используй её для эскалации».

---

## Валидация и частые ошибки

### Валидация при загрузке ZIP

При загрузке проверяется:

- Размер ZIP ≤ 500 МБ (настраивается через `competition_zip_max_bytes`).
- Количество файлов ≤ 5000.
- Нет `..`, абсолютных путей, symlink.
- Нет `__MACOSX/`, `.DS_Store`, `Thumbs.db`.
- `manifest.yaml` в корне.
- Все обязательные поля манифеста.
- `metadata` соответствует `type`.
- `container_port` не в списке зарезервированных
  (80, 443, 5173, 5432, 8000).
- `container_port` уникален в рамках соревнования.
- `Dockerfile` не содержит запрещённых инструкций.
- Базовый образ из allowlist (если флаг включён).
- Все `dependencies` существуют.
- Для `kind=static` — папка `public/` непуста.

### Частые ошибки

| Ошибка | Причина | Решение |
|---|---|---|
| `Invalid manifest` | Опечатка в `type` или `kind` | Проверьте допустимые значения |
| `container_port required for kind=docker` | Забыли указать порт | Добавьте `container_port: 5000` |
| `container_port must be empty for kind=static` | Указали порт для статики | Уберите поле |
| `Dockerfile not found` | Нет `Dockerfile` для `kind=docker` | Добавьте в корень ZIP |
| `public/ directory is empty` | Для `kind=static` нет файлов | Положите файлы в `public/` |
| `Base image ... is not in allowlist` | Базовый образ не разрешён | Используйте из списка или отключите allowlist |
| `Unsafe path in ZIP` | В архиве есть `../` | Пересоберите ZIP |
| `Symlinks are not allowed` | В ZIP есть symlink | Уберите symlink (`zip -r` без `-y`) |
| `Unknown dependencies: x` | Зависимость не существует | Загрузите сначала её, потом это задание |
| `Challenge cannot depend on itself` | Slug в `dependencies` совпадает с самим собой | Уберите |
| `container_port ... is reserved` | Использован порт платформы | Выберите 5000–9999 |
| `container_port ... is already used` | Порт занят другим заданием | Выберите другой |

### Как собрать ZIP правильно

```bash
# Внутри папки с manifest.yaml и app/ или public/:
cd my-challenge
zip -r ../my-challenge.zip .

# НЕ используйте zip -y (symlink) и не пакуйте саму папку целиком:
# zip -r challenge.zip my-challenge/   # <-- неправильно, manifest будет в подпапке
```

Правильно: `manifest.yaml` **в корне архива**.

Проверить:

```bash
unzip -l my-challenge.zip
# Archive: my-challenge.zip
#   Length      Date    Time    Name
# ---------  ---------- -----   ----
#       400  ...  manifest.yaml
#       120  ...  Dockerfile
#       800  ...  app/server.py
# ...
```

Если `manifest.yaml` в подпапке — распакуйте, пересоберите из корня.

---

## Чек-лист перед загрузкой

### Для всех типов

- [ ] `manifest.yaml` в корне ZIP.
- [ ] Slug — kebab-case, только латиница, цифры, дефис.
- [ ] `type` из допустимого списка.
- [ ] `kind` — `docker` или `static`.
- [ ] `flag` или `flag_hash` указан.
- [ ] `points` соответствует сложности (обычно 50–500).
- [ ] `description` понятен студенту и не содержит флаг.
- [ ] `visibility` выставлен корректно.
- [ ] `metadata` соответствует `type`.

### Для kind=docker

- [ ] `container_port` указан и не в зарезервированных.
- [ ] `Dockerfile` собирается локально (`docker build .`).
- [ ] Приложение слушает `0.0.0.0`, а не `127.0.0.1`.
- [ ] `container_port` совпадает с портом в `server.py`.
- [ ] Базовый образ из allowlist.
- [ ] Нет запрещённых инструкций в Dockerfile.
- [ ] `EXPOSE <container_port>` присутствует.
- [ ] Контейнер запускается от непривилегированного пользователя.
- [ ] Флаг не в открытом виде в коде, если стратегия `dynamic`.

### Для kind=static

- [ ] Папка `public/` непуста.
- [ ] Файлы не содержат флаг в открытом виде в неожиданных местах
      (если так задумано — ок).
- [ ] Флаг извлекается тем инструментом, который задуман.
- [ ] Формат флага явно описан в `description` (регистр, разделители).

### Ручная проверка

- [ ] Прочитайте задание как студент: понятна ли цель?
- [ ] Пройдите решение сами от начала до конца.
- [ ] Убедитесь, что подсказок достаточно.
- [ ] Проверьте, что флаг из описания совпадает с фактическим.

---

## Где хранить исходники заданий

Рекомендуемая структура репозитория:

```
challenges/
├── my-sqli-101/
│   ├── manifest.yaml
│   ├── Dockerfile
│   ├── app/
│   │   └── server.py
│   └── README.md              # заметки автора, не входит в ZIP
├── my-crypto-201/
│   ├── manifest.yaml
│   ├── public/
│   │   └── ciphertext.bin
│   ├── generator.py           # скрипт генерации артефакта
│   └── README.md
└── ...
```

`README.md` — для автора задания, не входит в ZIP. `generator.py` —
скрипт, который создаёт артефакты (PCAP, шифротекст, изображение), чтобы
при ротации флага легко было перегенерировать.

Собирайте ZIP автоматически:

```bash
#!/usr/bin/env bash
# scripts/build-challenge-zip.sh
SLUG="$1"
if [ -z "$SLUG" ]; then echo "Usage: $0 <slug>"; exit 1; fi
cd "challenges/$SLUG" || exit 1
zip -r "../../$SLUG.zip" manifest.yaml Dockerfile app public 2>/dev/null
echo "Built $SLUG.zip"
```

Запускайте: `scripts/build-challenge-zip.sh my-sqli-101`.

---

## Примеры готовых заданий

В репозитории есть готовые шаблоны для всех типов:

- `challenges/sqli-101/` — web (SQL injection, docker).
- `challenges/xss-101/` — web (reflected XSS, docker).
- `challenges/crypto-201/` — crypto (padding oracle, docker).
- `challenges/pcap-201/` — forensics (PCAP, docker).
- `challenges/stego-*` — stego (static).
- `challenges/binary-201/` — pwn (buffer overflow, docker).
- `challenges/subdomain-201/` — web (subdomain hunt, docker).
- `challenges/template/` — пустой шаблон.

Копируйте, меняйте, пересобирайте.