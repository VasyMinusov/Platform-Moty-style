"""
SecureNotes — JWT 201
"Сервис для хранения личных заметок" с JWT-аутентификацией.
Уязвимость: слабый секрет "secret123", и сервер принимает alg=none.
"""
import os
import base64
import hmac
import hashlib
import json
from flask import Flask, request, jsonify, render_template, make_response

app = Flask(__name__)
SECRET = "secret123"
FLAG = os.environ.get("FLAG", "flag{jwt_s3cr3t_1s_t00_w34k}")

users = {"alice": {"password": "alice123", "notes": ["Первый день в компании."], "role": "user"}}

def b64url_encode(data):
    return base64.urlsafe_b64encode(data.encode()).rstrip(b'=').decode()

def b64url_decode(data):
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data).decode()

def sign_jwt(header, payload):
    msg = f"{b64url_encode(json.dumps(header))}.{b64url_encode(json.dumps(payload))}"
    sig = hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}.{b64url_encode(sig)}"

def verify_jwt(token):
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header = json.loads(b64url_decode(parts[0]))
        payload = json.loads(b64url_decode(parts[1]))
        if header.get('alg') == 'none':
            return payload
        msg = f"{parts[0]}.{parts[1]}"
        expected = hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, b64url_decode(parts[2])):
            return payload
        return None
    except Exception:
        return None

def get_user():
    token = request.cookies.get('token')
    if not token:
        return None
    payload = verify_jwt(token)
    if not payload:
        return None
    return payload.get('username')

@app.route("/")
def index():
    user = get_user()
    if not user:
        return render_template("login.html")
    notes = users.get(user, {}).get('notes', [])
    return render_template("notes.html", username=user, notes=notes, role=users.get(user, {}).get('role', 'user'))

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if username in users:
        return jsonify({"error": "User already exists"}), 409
    users[username] = {"password": password, "notes": [], "role": "user"}
    return jsonify({"ok": True})

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    user = users.get(username)
    if not user or user['password'] != password:
        return jsonify({"error": "Invalid credentials"}), 401

    payload = {"username": username, "role": user['role']}
    header = {"alg": "HS256", "typ": "JWT"}
    token = sign_jwt(header, payload)
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie('token', token, httponly=False, samesite='Lax')
    return resp

@app.route("/api/notes", methods=["GET", "POST"])
def notes():
    username = get_user()
    if not username:
        return jsonify({"error": "Unauthorized"}), 401
    if request.method == "GET":
        return jsonify({"notes": users.get(username, {}).get('notes', [])})
    data = request.json or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({"error": "Empty note"}), 400
    users[username]['notes'].append(text)
    return jsonify({"ok": True})

@app.route("/api/flag")
def flag():
    username = get_user()
    if not username:
        return jsonify({"error": "Unauthorized"}), 401
    # УЯЗВИМОСТЬ: проверка роли только по JWT, но роль можно подделать через weak secret или alg=none
    if users.get(username, {}).get('role') != 'admin':
        return jsonify({"error": "Admin only"}), 403
    return jsonify({"flag": FLAG})

@app.route("/logout")
def logout():
    resp = make_response(render_template("login.html"))
    resp.set_cookie('token', '', expires=0)
    return resp

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
