FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends whois dnsutils iputils-ping \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1001 appuser
WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

USER appuser
EXPOSE 5000

CMD ["python", "server.py"]
