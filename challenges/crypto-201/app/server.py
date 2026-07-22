"""
Padding Oracle 201
Сервер шифрует данные AES-128-CBC с PKCS7 padding.
Endpoint /check возвращает только valid/invalid — это и есть padding oracle.
Студент должен расшифровать флаг, используя oracle.
"""
import os
import secrets
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
FLAG = os.environ.get("FLAG", "flag{p4dd1ng_0r4cl3_4tt4ck_4w3s0m3}")

# 16-байтный случайный ключ, генерируется при старте контейнера
KEY = secrets.token_bytes(16)


def encrypt(plaintext: bytes) -> bytes:
    iv = secrets.token_bytes(16)
    cipher = AES.new(KEY, AES.MODE_CBC, iv)
    ct = cipher.encrypt(pad(plaintext, AES.block_size))
    return iv + ct


def decrypt_is_valid(data: bytes) -> bool:
    if len(data) % AES.block_size != 0 or len(data) < 2 * AES.block_size:
        return False
    iv = data[:16]
    ct = data[16:]
    try:
        cipher = AES.new(KEY, AES.MODE_CBC, iv)
        pt = cipher.decrypt(ct)
        unpad(pt, AES.block_size)
        return True
    except ValueError:
        return False


@app.route("/")
def index():
    return render_template_string("""
    <h2>Padding Oracle 201</h2>
    <p>Сервер шифрует сообщения AES-128-CBC. Проверьте любой шифротекст —
    сервер скажет только valid/invalid.</p>
    <ul>
      <li><b>GET /encrypt?msg=...</b> — зашифровать строку (hex ответ)</li>
      <li><b>GET /check?data=...</b> — проверить шифротекст (hex)</li>
      <li><b>GET /flag</b> — получить зашифрованный флаг</li>
    </ul>
    """)


@app.route("/encrypt")
def encrypt_endpoint():
    msg = request.args.get("msg", "")
    ct = encrypt(msg.encode("utf-8"))
    return jsonify({"hex": ct.hex()})


@app.route("/check")
def check_endpoint():
    data = request.args.get("data", "")
    try:
        raw = bytes.fromhex(data)
    except ValueError:
        return jsonify({"valid": False, "error": "invalid hex"})
    return jsonify({"valid": decrypt_is_valid(raw)})


@app.route("/flag")
def flag_endpoint():
    ct = encrypt(FLAG.encode("utf-8"))
    return jsonify({"hex": ct.hex()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
