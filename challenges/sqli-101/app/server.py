"""
Учебное уязвимое веб-приложение (SQL Injection).
ВНИМАНИЕ: намеренно уязвимый код, только для контролируемой учебной среды.
Изолирован в собственном Docker-контейнере без доступа к остальной инфраструктуре.
"""
import os
import sqlite3

from flask import Flask, request, render_template_string

app = Flask(__name__)
DB_PATH = "/tmp/challenge.db"
FLAG = os.environ.get("FLAG", "flag{sql_1nj3ct10n_1s_2asy}")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS users (username TEXT, password TEXT)")
    conn.execute("DELETE FROM users")
    conn.execute("INSERT INTO users VALUES ('admin', 'super_secret_password_123')")
    conn.commit()
    conn.close()


LOGIN_PAGE = """
<h2>Учебный портал входа</h2>
<form method="POST">
  Логин: <input name="username"><br>
  Пароль: <input name="password" type="password"><br>
  <button type="submit">Войти</button>
</form>
{% if message %}<p>{{ message }}</p>{% endif %}
"""


@app.route("/", methods=["GET", "POST"])
def login():
    message = ""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        # УЯЗВИМОСТЬ: конкатенация строк в SQL-запрос без параметризации.
        conn = sqlite3.connect(DB_PATH)
        query = f"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'"
        try:
            cursor = conn.execute(query)
            row = cursor.fetchone()
        except sqlite3.Error as e:
            row = None
            message = f"DB error: {e}"
        conn.close()

        if row:
            message = f"Добро пожаловать, {row[0]}! Флаг: {FLAG}"
        else:
            message = "Неверный логин или пароль."

    return render_template_string(LOGIN_PAGE, message=message)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
