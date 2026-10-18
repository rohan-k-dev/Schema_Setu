# SchemeSetu backend image (FastAPI + LangGraph).
# Build context: repository root —  docker build -f backend/Dockerfile .
# The image mirrors the repo layout (backend/, scripts/, data/) because the app
# resolves the corpus and Knowledge Graph snapshot relative to it.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/backend

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

# Application code, maintenance scripts and the canonical, versioned data
COPY backend/ /srv/backend/
COPY scripts/ /srv/scripts/
COPY data/validated/ /srv/data/validated/
COPY data/metadata/ /srv/data/metadata/
COPY data/graph/current/ /srv/data/graph/current/

RUN useradd --create-home --uid 10001 appuser && chown -R appuser /srv/data
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
