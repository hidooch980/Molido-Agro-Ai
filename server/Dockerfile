FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MOLIDO_DB_PATH=/data/molido.sqlite3
WORKDIR /srv/molido
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --system --uid 10001 molido && mkdir -p /data && chown -R molido:molido /data /srv/molido
COPY app.py sensor_api.py chirpstack_bridge.py ./
USER molido
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
