"""
Учебное уязвимое веб-приложение — КОМПЛЕКСНОЕ ЗАДАНИЕ (цепочка уязвимостей).
ВНИМАНИЕ: намеренно уязвимый код, только для контролируемой учебной среды.

Легенда: внутренний "хелпдеск" со службой мониторинга. Чтобы получить флаг,
нужно пройти цепочку из трёх шагов:

  1. IDOR       — /api/users/<id> отдаёт профиль ЛЮБОГО пользователя
                  любому авторизованному аккаунту, включая служебный
                  аккаунт "svc-monitor" и его api_key.
  2. SSRF       — с этим api_key можно дёрнуть /api/monitor/check?url=...,
                  сервис-монитор ходит по указанному URL от имени бэкенда.
                  Это позволяет достучаться до внутреннего сервиса
                  диагностики, который слушает ТОЛЬКО 127.0.0.1 и не
                  проброшен наружу через container_port.
  3. RCE        — внутренний сервис диагностики (/debug/check?host=...)
                  передаёт host прямо в shell-команду curl без всякой
                  фильтрации — классическая command injection.

Итоговый payload собирает все три шага в один запрос к публичному
приложению — ровно то, что должен произвести пентестер в реальной цепочке.
"""
import os
import subprocess
import threading

import requests
from flask import Flask, request, jsonify, session, redirect

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-not-for-prod")
# Сам FLAG в переменной окружения приложению не нужен — конечная цель
# атаки - прочитать /flag.txt через RCE во внутреннем сервисе диагностики.
# Файл создаётся на этапе сборки образа (см. Dockerfile), т.к. в рантайме
# процесс работает от непривилегированного appuser.

# --- "База данных" --------------------------------------------------------
USERS = {
    1: {"username": "svc-monitor", "password": "not-used-directly", "role": "service",
        "api_key": "svcmon_9f1c2b6a7d4e"},
    2: {"username": "admin", "password": "admin_do_not_use_2024", "role": "admin",
        "api_key": "admin_2b8e6a1f5c9d"},
}
_next_id = 3
_username_to_id = {u["username"]: uid for uid, u in USERS.items()}


def _register(username: str, password: str) -> int:
    global _next_id
    uid = _next_id
    _next_id += 1
    USERS[uid] = {"username": username, "password": password, "role": "user",
                  "api_key": f"user_{uid}_key"}
    _username_to_id[username] = uid
    return uid


# --- Публичное приложение (порт 5000, проброшен наружу) --------------------

INDEX = """
<h2>Внутренний хелпдеск</h2>
<p>Зарегистрируйтесь и войдите, чтобы увидеть свой профиль.</p>
<p><a href="/register">Регистрация</a> | <a href="/login">Вход</a></p>
"""


@app.route("/")
def index():
    return INDEX


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return '<form method="post">Логин: <input name="username">' \
               'Пароль: <input name="password">' \
               '<button>Зарегистрироваться</button></form>'
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not username or username in _username_to_id:
        return "Имя занято или пустое", 400
    uid = _register(username, password)
    session["user_id"] = uid
    return redirect("/me")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return '<form method="post">Логин: <input name="username">' \
               'Пароль: <input name="password" type="password">' \
               '<button>Войти</button></form>'
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    uid = _username_to_id.get(username)
    if uid is not None and USERS[uid]["password"] == password:
        session["user_id"] = uid
        return redirect("/me")
    return "Неверные данные", 401


@app.route("/me")
def me():
    uid = session.get("user_id")
    if uid is None:
        return redirect("/login")
    return jsonify({"your_id": uid, "hint": "Попробуйте GET /api/users/<id> с другими id"})


@app.route("/api/users/<int:user_id>")
def api_user(user_id):
    if session.get("user_id") is None:
        return jsonify({"error": "unauthorized"}), 401
    user = USERS.get(user_id)
    if not user:
        return jsonify({"error": "not found"}), 404
    # УЯЗВИМОСТЬ (шаг 1, IDOR): нет проверки, что user_id == session["user_id"].
    # Любой залогиненный аккаунт может прочитать чужой профиль, включая
    # служебный аккаунт svc-monitor (id=1) и его api_key.
    return jsonify(user)


@app.route("/api/monitor/check")
def monitor_check():
    api_key = request.headers.get("X-API-Key", "")
    # Доступ к этому эндпоинту разрешён только сервисному api_key.
    if api_key != USERS[1]["api_key"]:
        return jsonify({"error": "invalid api key"}), 403

    url = request.args.get("url")
    if not url:
        return jsonify({"error": "url required"}), 400

    # УЯЗВИМОСТЬ (шаг 2, SSRF): сервис-монитор ходит по любому URL,
    # включая внутренние адреса (127.0.0.1 и т.д.), не проброшенные наружу.
    try:
        resp = requests.get(url, timeout=5)
        return jsonify({"status_code": resp.status_code, "body": resp.text[:4000]})
    except requests.RequestException as exc:
        return jsonify({"error": str(exc)}), 502


# --- Внутренний сервис диагностики (порт 6001, слушает ТОЛЬКО 127.0.0.1) ---
# Не публикуется в docker-compose/оркестраторе наружу — единственный способ
# достучаться до него снаружи задания это SSRF через /api/monitor/check.

internal_app = Flask("internal-debug")


@internal_app.route("/debug/check")
def debug_check():
    host = request.args.get("host", "")
    if not host:
        return jsonify({"hint": "Используйте параметр host. Пример: localhost:5000"})
    # УЯЗВИМОСТЬ (шаг 3, command injection): host подставляется прямо в
    # shell-команду без экранирования и без allowlist символов.
    cmd = f"curl -s -o /dev/null -w 'HTTP:%{{http_code}}' --max-time 2 http://{host}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
    return jsonify({"cmd_stdout": result.stdout, "cmd_stderr": result.stderr})


def _run_internal():
    internal_app.run(host="127.0.0.1", port=6001)


if __name__ == "__main__":
    threading.Thread(target=_run_internal, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)