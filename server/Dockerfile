# Safqa Cloud - build from the repository root:  docker build -f server/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app SAFQA_ENV=production PORT=8000 WEB_CONCURRENCY=2

WORKDIR /app
COPY server/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Only what the server needs: its own code + the shared plan definitions.
COPY server/safqa_cloud /app/safqa_cloud
COPY src/safqa/__init__.py src/safqa/billing.py /app/safqa/

# Never run as root.
RUN useradd --create-home --uid 10001 safqa
USER safqa

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'), timeout=4)"
CMD ["sh", "-c", "exec uvicorn safqa_cloud.app:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips='*'"]
