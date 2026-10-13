FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1001 appuser
WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Собираем бинарь без защит, чтобы адреса были фиксированными
RUN gcc -fno-stack-protector -no-pie -z execstack -o challenge challenge.c \
    && chmod +x challenge

# Точка входа: пишет флаг в /tmp/flag.txt из переменной окружения FLAG
# (которую подставляет оркестратор для динамических флагов), а если
# переменной нет — использует статический дефолт.
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && chmod -R a+rX /app

USER appuser
EXPOSE 5000

ENTRYPOINT ["/entrypoint.sh"]