"""
Учебное уязвимое веб-приложение (Path Traversal).
ВНИМАНИЕ: намеренно уязвимый код, только для контролируемой учебной среды.
"""
import os
from flask import Flask, request, send_file, abort

app = Flask(__name__)

BASE_DIR = "/app/docs"
FLAG = os.environ.get("FLAG", "flag{path_travers4l_pwned}")

INDEX = """
<h2>Библиотека документов</h2>
<ul>
  <li><a href="/view?file=welcome.txt">welcome.txt</a></li>
  <li><a href="/view?file=changelog.txt">changelog.txt</a></li>
</ul>
"""


@app.route("/")
def index():
    return INDEX + "<!-- Подсказка: системный администратор оставил важный файл в корне файловой системы -->"

@app.route("/view")
def view():
    filename = request.args.get("file", "welcome.txt")
    # УЯЗВИМОСТЬ: имя файла подставляется в путь без проверки на "..".
    # Ожидается, что пользователь выйдет за пределы BASE_DIR и прочитает
    # /flag.txt, лежащий вне разрешённой директории.
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="text/plain")


if __name__ == "__main__":
    # Флаг и документы создаются на этапе сборки образа (см. Dockerfile),
    # т.к. приложение работает от непривилегированного пользователя и не
    # имеет прав на запись в "/" во время выполнения.
    app.run(host="0.0.0.0", port=5000)