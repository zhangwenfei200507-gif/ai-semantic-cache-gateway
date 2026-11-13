FROM python:3.11-slim

ARG EMBEDDING_MODEL_REVISION=7999e1d3359715c523056ef9478215996d62a620

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/huggingface \
    HF_HUB_CACHE=/opt/huggingface/hub \
    EMBEDDING_MODEL_PATH=/opt/models/bge-small-zh-v1.5 \
    EMBEDDING_MODEL_LOCAL_ONLY=true

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download an immutable model snapshot at build time. The runtime image does
# not need network access to load Semantic Cache embeddings.
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='BAAI/bge-small-zh-v1.5', revision='${EMBEDDING_MODEL_REVISION}', local_dir='/opt/models/bge-small-zh-v1.5')"

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY app ./app
COPY config/providers.yaml ./config/providers.yaml
COPY frontend ./frontend

EXPOSE 8000

# Railway can use the same readiness contract as local Docker orchestration.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/ready', timeout=4)"

CMD ["sh", "-c", "uvicorn app.api.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
