import os
from flask import Flask, request, render_template_string

app = Flask(__name__)
FLAG = os.environ.get("FLAG", "flag{xxe_0uts1de_th3_b0x}")

PAGE = """
<h2>Система отчётов</h2>
<form method="POST" enctype="text/plain">
  <textarea name="xml" rows="10" cols="50" placeholder="Вставьте XML отчёт..."></textarea><br>
  <button type="submit">Обработать</button>
</form>
{% if result %}
<h3>Результат:</h3>
<pre>{{ result }}</pre>
{% endif %}
"""

import xml.etree.ElementTree as ET

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    if request.method == "POST":
        xml_data = request.get_data(as_text=True)
        try:
            # УЯЗВИМОСТЬ: ET.fromstring разрешает внешние сущности по умолчанию
            root = ET.fromstring(xml_data)
            result = ET.tostring(root, encoding='unicode')
        except Exception as e:
            result = f"Ошибка: {e}"
    return render_template_string(PAGE, result=result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)