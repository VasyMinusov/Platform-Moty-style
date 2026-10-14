FROM python:3.12-slim

RUN useradd -m -u 1001 appuser
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/

USER appuser
EXPOSE 5060

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5060"]