"""
Учебный веб-сервер для задания PCAP Forensics 201.
Отдаёт сгенерированный PCAP-файл студенту.
"""
import os
from flask import Flask, send_from_directory, render_template_string

app = Flask(__name__)

@app.route("/")
def index():
    return render_template_string("""
    <h2>PCAP Forensics 201</h2>
    <p>Администратор сделал захват трафика и сохранил его в файл.</p>
    <p>Скачайте PCAP, откройте в Wireshark и найдите скрытые учётные данные.</p>
    <a href="/capture.pcap" download>Скачать capture.pcap</a>
    """)

@app.route("/capture.pcap")
def download_pcap():
    return send_from_directory("static", "capture.pcap")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
