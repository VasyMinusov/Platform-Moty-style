FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1001 appuser
WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Флаг лежит в /flag.txt (за пределами /app), доступен только через
# успешную RCE во внутреннем диагностическом сервисе (шаг 3 цепочки).
RUN echo "flag{chain_re4ction_idor_ssrf_rce}" > /flag.txt \
    && chmod 644 /flag.txt \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 5000

CMD ["python", "server.py"]