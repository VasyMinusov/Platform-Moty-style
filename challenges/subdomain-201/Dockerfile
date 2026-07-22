FROM python:3.12-slim

RUN useradd -m -u 1001 appuser
WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

RUN chmod -R a+rX /app

USER appuser
EXPOSE 5000

CMD ["python", "server.py"]
