FROM python:3.12-slim

# Флаг передаётся в образ, чтобы значение совпадало с манифестом.
ENV FLAG=flag{p4dd1ng_0r4cl3_4tt4ck_4w3s0m3}

RUN useradd -m -u 1001 appuser
WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

RUN chmod -R a+rX /app

USER appuser
EXPOSE 5000

CMD ["python", "server.py"]