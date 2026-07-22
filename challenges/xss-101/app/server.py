"""
Учебное уязвимое веб-приложение (Reflected XSS).
ВНИМАНИЕ: намеренно уязвимый код, только для контролируемой учебной среды.
"""
import os
from flask import Flask, request

app = Flask(__name__)
FLAG = os.environ.get("FLAG", "flag{xss_r3fl3ct3d_and_f0und}")

PAGE = """
<h2>Гостевая книга</h2>
<form method="GET">
  Ваше имя: <input name="name">
  <button type="submit">Оставить запись</button>
</form>
<div id="output">
  Привет, {name}!
</div>
<script>
  // Флаг выдаётся, если во внедрённом скрипте вызвана функция solved()
  window.solved = function() {{
    document.getElementById('output').innerHTML += '<p>Флаг: {flag}</p>';
  }}
</script>
"""


@app.route("/")
def guestbook():
    # УЯЗВИМОСТЬ: параметр name подставляется в HTML без экранирования.
    name = request.args.get("name", "гость")
    return PAGE.format(name=name, flag=FLAG)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
