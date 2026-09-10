FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY app ./app

EXPOSE 8004
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004", "--limit-concurrency", "8", "--no-proxy-headers"]
