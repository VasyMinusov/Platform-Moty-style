"""
NetTools — Command Injection 201
"Сетевой инструментарий администратора" для проверки доменов.
Уязвимость: user input подставляется в shell-команду без экранирования.
"""
import os
import subprocess
from flask import Flask, request, render_template, jsonify

app = Flask(__name__)
FLAG = os.environ.get("FLAG", "flag{cmd_1nj3ct10n_n3tt00ls}")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/lookup", methods=["POST"])
def lookup():
    tool = request.form.get("tool", "")
    target = request.form.get("target", "").strip()

    if not target:
        return jsonify({"error": "Target is required"}), 400

    if tool == "whois":
        # УЯЗВИМОСТЬ: command injection через неотфильтрованный target
        cmd = f"whois {target}"
    elif tool == "ping":
        cmd = f"ping -c 1 {target}"
    elif tool == "dig":
        cmd = f"dig {target}"
    else:
        return jsonify({"error": "Unknown tool"}), 400

    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, timeout=10)
        output = output.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError as e:
        output = e.output.decode("utf-8", errors="replace") if e.output else str(e)
    except subprocess.TimeoutExpired:
        output = "Command timed out"

    return jsonify({"tool": tool, "target": target, "output": output})

@app.route("/api/flag")
def flag():
    # Флаг лежит в env, но доступен только через command injection
    return jsonify({"hint": "The flag is in the environment of the web server process."})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
