"""
Учебное уязвимое веб-приложение (IDOR — Insecure Direct Object Reference).
ВНИМАНИЕ: намеренно уязвимый код, только для контролируемой учебной среды.
"""
import os
from flask import Flask, request, jsonify, session, redirect

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-not-for-prod")
FLAG = os.environ.get("FLAG", "flag{idor_1s_everywhere_2024}")

# "База данных" заметок пользователей. Заметка id=1 принадлежит admin
# и содержит флаг — обычный пользователь не должен иметь к ней доступ.
NOTES = {
    1: {"owner": "admin", "title": "Резервные коды", "body": f"Не публикуйте: {FLAG}"},
    2: {"owner": "guest", "title": "Список покупок", "body": "Молоко, хлеб, яйца"},
}

USERS = {"guest": "guest123"}
NEXT_NOTE_ID = 3

PAGE = """
<h2>Мои заметки</h2>
<p>Вы вошли как: {user}</p>
<ul>{items}</ul>
<p>Открыть заметку: <a href="/notes/2">/notes/2</a></p>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return '<form method="post">Логин: <input name="username">' \
               '<input type="hidden" name="password" value="guest123">' \
               '<button>Войти</button></form>'
    username = request.form.get("username", "guest")
    if username in USERS:
        session["user"] = username
        return redirect("/")
    return "Неизвестный пользователь", 401


@app.route("/")
def index():
    user = session.get("user")
    if not user:
        return redirect("/login")
    my_notes = [n for n in NOTES.values() if n["owner"] == user]
    items = "".join(f"<li>{n['title']}</li>" for n in my_notes)
    return PAGE.format(user=user, items=items)


@app.route("/notes/<int:note_id>")
def get_note(note_id):
    if not session.get("user"):
        return redirect("/login")
    note = NOTES.get(note_id)
    if not note:
        return jsonify({"error": "not found"}), 404
    # УЯЗВИМОСТЬ: не проверяется, что note["owner"] == session["user"].
    # Любой авторизованный пользователь может открыть чужую заметку,
    # просто подобрав/перебрав id.
    return jsonify(note)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)