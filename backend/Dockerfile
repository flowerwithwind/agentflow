# AgentFlow backend image
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENTFLOW_DATA_DIR=/data

WORKDIR /app

COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY VERSION /VERSION

EXPOSE 8020

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8020/api/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]
