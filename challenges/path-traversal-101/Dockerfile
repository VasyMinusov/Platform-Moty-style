FROM python:3.12-slim

RUN useradd -m -u 1001 appuser
WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Флаг лежит вне BASE_DIR ("/app/docs"), доступен только через traversal.
# Создаётся на этапе сборки (от root), т.к. в рантайме процесс работает
# от непривилегированного appuser и не может писать в "/".
RUN mkdir -p /app/docs \
    && echo "Добро пожаловать в библиотеку документов." > /app/docs/welcome.txt \
    && printf "v1.0 - первый релиз\nv1.1 - мелкие правки\n" > /app/docs/changelog.txt \
    && echo "flag{path_travers4l_pwned}" > /flag.txt \
    && chmod 644 /flag.txt \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 5000

CMD ["python", "server.py"]