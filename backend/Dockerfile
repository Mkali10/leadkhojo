# Build context is the repository root, so `rules/` is reachable.
#
#     docker build -f backend/Dockerfile .

FROM python:3.12-slim AS builder

WORKDIR /app

# Dependencies first, so editing source does not re-resolve the world.
COPY backend/pyproject.toml ./backend/
COPY backend/src ./backend/src

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/venv/bin/pip install --no-cache-dir ./backend


FROM python:3.12-slim

# Never run as root. A crawler is a program that pulls untrusted bytes off
# the internet and parses them; assume one day a parser has a bad day.
RUN useradd --create-home --uid 10001 leadkhojo

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY rules ./rules

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LK_RULES_DIR=/app/rules

USER leadkhojo

EXPOSE 8000

# Liveness only. Readiness (/readyz) is what a load balancer should poll;
# using it here would make the container restart during a database blip.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "leadkhojo.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
