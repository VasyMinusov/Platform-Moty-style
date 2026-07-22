"""
Комплексное задание: JWT None Algorithm → SSTI → Pickle Deserialization RCE
Цепочка из 3 уязвимостей, каждая ведёт к следующей.
"""
import os
import pickle
import base64
import json
import hmac
import hashlib
from flask import Flask, request, jsonify, render_template_string, make_response

app = Flask(__name__)
SECRET = "vault_secret_2024"  # Секрет для нормального JWT
FLAG = os.environ.get("FLAG", "flag{v4ult_br0k3n_1n_3v3ry_l4y3r}")

# --- Этап 1: JWT с уязвимостью "none" algorithm ---
def b64encode(data):
    return base64.urlsafe_b64encode(data.encode()).rstrip(b'=').decode()

def b64decode(data):
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data).decode()

def sign_jwt(header, payload, secret):
    msg = f"{b64encode(json.dumps(header))}.{b64encode(json.dumps(payload))}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}.{b64encode(sig)}"

def verify_jwt(token):
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header = json.loads(b64decode(parts[0]))
        payload = json.loads(b64decode(parts[1]))
        
        # УЯЗВИМОСТЬ 1: если alg == "none", подпись не проверяется!
        if header.get('alg') == 'none':
            return payload
        
        # Нормальная проверка
        msg = f"{parts[0]}.{parts[1]}"
        expected_sig = hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
        actual_sig = b64decode(parts[2])
        if expected_sig == actual_sig:
            return payload
        return None
    except Exception:
        return None

# --- Этап 2: SSTI в шаблоне отчётов ---
REPORT_TEMPLATE = """
<h2>Отчёт хранилища</h2>
<p>Пользователь: {{ user }}</p>
<p>Данные:</p>
<pre>{{ data }}</pre>
<p>Статус: OK</p>
"""

# --- Этап 3: Кэш через pickle (deserialization) ---
CACHE = {}

@app.route("/")
def index():
    return """
    <h2>🔐 The Vault</h2>
    <p><a href="/login">Вход</a> | <a href="/vault">Хранилище</a></p>
    """

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return '''
        <form method="post">
          <input name="username" placeholder="логин">
          <input name="password" type="password" placeholder="пароль">
          <button>Войти</button>
        </form>
        <p>Подсказка: попробуйте alg=none в JWT...</p>
        '''
    username = request.form.get("username", "guest")
    payload = {"user": username, "role": "user"}
    header = {"alg": "HS256", "typ": "JWT"}
    token = sign_jwt(header, payload, SECRET)
    resp = make_response(jsonify({"token": token, "hint": "Перейдите /vault с токеном в cookie"}))
    resp.set_cookie("token", token)
    return resp

@app.route("/vault")
def vault():
    token = request.cookies.get("token", "")
    payload = verify_jwt(token)
    if not payload:
        return jsonify({"error": "Invalid token"}), 401
    
    user = payload.get("user", "unknown")
    role = payload.get("role", "user")
    
    # Если роль admin — показываем флаг (но как её получить?)
    if role == "admin":
        return jsonify({"flag": FLAG, "message": "Добро пожаловать, администратор!"})
    
    # Обычный пользователь видит форму отчёта
    return render_template_string("""
    <h2>Хранилище {{ user }}</h2>
    <p>Роль: {{ role }}</p>
    <form method="post" action="/vault/report">
      <textarea name="data" placeholder="Введите данные для отчёта..."></textarea><br>
      <button>Сгенерировать отчёт</button>
    </form>
    <form method="post" action="/vault/cache">
      <input name="key" placeholder="ключ кэша">
      <input name="value" placeholder="значение (base64)">
      <button>Сохранить в кэш</button>
    </form>
    """, user=user, role=role)

@app.route("/vault/report", methods=["POST"])
def report():
    token = request.cookies.get("token", "")
    payload = verify_jwt(token)
    if not payload:
        return jsonify({"error": "Invalid token"}), 401
    
    user = payload.get("user", "unknown")
    data = request.form.get("data", "")
    
    # УЯЗВИМОСТЬ 2: SSTI — данные подставляются в шаблон напрямую
    # Пейлоад: {{ ''.__class__.__mro__[1].__subclasses__()[137].__init__.__globals__['__builtins__']['__import__']('os').popen('id').read() }}
    template = REPORT_TEMPLATE.replace("{{ data }}", data)
    return render_template_string(template, user=user)

@app.route("/vault/cache", methods=["POST"])
def cache():
    token = request.cookies.get("token", "")
    payload = verify_jwt(token)
    if not payload:
        return jsonify({"error": "Invalid token"}), 401
    
    key = request.form.get("key", "")
    value_b64 = request.form.get("value", "")
    
    # УЯЗВИМОСТЬ 3: Deserialization — pickle.loads на невалидированных данных
    try:
        value = pickle.loads(base64.b64decode(value_b64))
        CACHE[key] = value
        return jsonify({"status": "saved", "key": key})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/vault/cache/<key>")
def get_cache(key):
    token = request.cookies.get("token", "")
    payload = verify_jwt(token)
    if not payload:
        return jsonify({"error": "Invalid token"}), 401
    
    if key in CACHE:
        return jsonify({"key": key, "value": str(CACHE[key])})
    return jsonify({"error": "not found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)