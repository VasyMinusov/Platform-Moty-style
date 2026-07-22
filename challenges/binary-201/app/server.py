"""
Buffer Overflow 201 — веб-обёртка вокруг уязвимого бинаря.
Студент отправляет payload, сервер запускает бинарь с этим вводом
и возвращает stdout/stderr.
"""
import os
import base64
import subprocess
from flask import Flask, request, jsonify, send_from_directory, render_template_string

app = Flask(__name__)

@app.route("/")
def index():
    return render_template_string("""
    <h2>Buffer Overflow 201</h2>
    <p>Старый бинарный сервис читает ввод через gets().\n
    Внутри есть функция, печатающая флаг.\n
    Перезапишите адрес возврата и вызовите её.</p>
    <ul>
      <li><b>GET /challenge</b> — скачать ELF-бинарь</li>
      <li><b>POST /run</b> — отправить payload (base64 stdin) и получить вывод</li>
    </ul>
    """)

@app.route("/challenge")
def download_binary():
    return send_from_directory(".", "challenge", as_attachment=True, mimetype="application/octet-stream")

@app.route("/run", methods=["POST"])
def run_binary():
    data = request.get_json(force=True, silent=True) or {}
    b64_input = data.get("input", "")
    try:
        user_input = base64.b64decode(b64_input)
    except Exception as e:
        return jsonify({"error": f"invalid base64: {e}"}), 400

    try:
        proc = subprocess.run(
            ["./challenge"],
            input=user_input,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
        return jsonify({
            "stdout": proc.stdout.decode("utf-8", errors="replace"),
            "stderr": proc.stderr.decode("utf-8", errors="replace"),
            "returncode": proc.returncode,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "timeout"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
