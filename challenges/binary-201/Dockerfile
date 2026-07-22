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

# Флаг для чтения бинарем
ARG FLAG=flag{b0f_r3tw1n_4_sm00th_v1ct0ry}
RUN echo "$FLAG" > /flag.txt && chmod 644 /flag.txt

RUN chmod -R a+rX /app

USER appuser
EXPOSE 5000

CMD ["python", "server.py"]
