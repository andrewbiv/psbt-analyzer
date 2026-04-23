# syntax=docker/dockerfile:1.7

############################
# Stage 1 — build wheel
############################
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN pip install --upgrade pip build

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m build --wheel --outdir /wheels

############################
# Stage 2 — runtime
############################
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    PSBT_ASSET_ROOT=/app

RUN groupadd --system --gid 1001 app \
    && useradd  --system --uid 1001 --gid app --home /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install /wheels/*.whl && rm -rf /wheels

COPY templates ./templates
COPY static    ./static

RUN chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3); sys.exit(0 if r.status==200 else 1)"

CMD ["sh", "-c", "exec uvicorn psbt_tool.api.main:app --host ${HOST} --port ${PORT}"]
