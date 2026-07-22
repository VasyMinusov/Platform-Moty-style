"""
CloudPaste — SSRF 201
"Сервис проверки доступности веб-страниц" для внутреннего портала компании.
Намеренно уязвим: позволяет запросы к внутренним адресам (127.0.0.1, 10.0.0.0/8).
"""
import os
import re
import urllib.parse
from flask import Flask, request, render_template, jsonify
import requests

app = Flask(__name__)
FLAG = os.environ.get("FLAG", "flag{ssrf_cl0udp4st3_1nt3rn4l}")

# Имитируем внутренний сервис, доступный только с localhost
@app.route("/internal/flag")
def internal_flag():
    remote = request.remote_addr
    if remote not in ("127.0.0.1", "::1"):
        return jsonify({"error": "Forbidden: internal only"}), 403
    return jsonify({"secret": FLAG})

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/fetch", methods=["POST"])
def fetch():
    url = request.form.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    # Разрешаем схемы http/https
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return jsonify({"error": "Only http and https URLs allowed"}), 400

    # Фильтр "хостов" наивный и легко обходится (через DNS, IP-обходы и т.д.)
    blocked = re.compile(r"^(127\.0\.0\.1|localhost|::1|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|0\.0\.0\.0)", re.I)
    if blocked.match(parsed.hostname or ""):
        return jsonify({"error": "Access to internal network is forbidden"}), 403

    try:
        # УЯЗВИМОСТЬ: запросы выполняются сервером, без проверки redirect'ов на внутренние адреса
        resp = requests.get(url, timeout=5, allow_redirects=True, headers={"User-Agent": "CloudPaste/1.0"})
        content = resp.text[:2000]
        return jsonify({"status": resp.status_code, "headers": dict(resp.headers), "body": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
