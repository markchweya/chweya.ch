# Multi-stage build.
#
# The web image and the worker image differ: only the worker needs the
# extraction and OCR toolchain, and shipping Tesseract and Poppler in the
# public-facing container would add attack surface for no benefit.

# --------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Run as a non-root user. A container process that does not need root should
# not have it, and this one only reads its own source and writes to storage.
RUN groupadd --system --gid 1001 dumi \
    && useradd --system --uid 1001 --gid dumi --home /srv --shell /usr/sbin/nologin dumi

COPY pyproject.toml ./
COPY app ./app

# --------------------------------------------------------------------------
FROM base AS development

RUN pip install --no-cache-dir -e ".[dev]"
COPY migrations ./migrations
COPY alembic.ini ./
RUN mkdir -p /srv/storage && chown -R dumi:dumi /srv/storage
USER dumi
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# --------------------------------------------------------------------------
FROM base AS worker

# Extraction and OCR dependencies. tesseract language packs cover the four
# supported languages; without them OCR silently produces nonsense for
# accented French and Italian text.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libmagic1 \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-deu \
        tesseract-ocr-eng \
        tesseract-ocr-fra \
        tesseract-ocr-ita \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -e ".[ingest,embed,ocr]"
RUN mkdir -p /srv/storage && chown -R dumi:dumi /srv/storage
USER dumi
CMD ["rq", "worker", "ingest", "embed", "default"]

# --------------------------------------------------------------------------
FROM base AS production

RUN pip install --no-cache-dir .
COPY migrations ./migrations
COPY alembic.ini ./
RUN mkdir -p /srv/storage && chown -R dumi:dumi /srv/storage
USER dumi
EXPOSE 8000
# No --reload, and workers sized by the deployment. See docs/deployment.md.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
