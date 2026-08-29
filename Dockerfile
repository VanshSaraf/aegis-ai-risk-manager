FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY apps ./apps
COPY packages ./packages
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install .

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn apps.api.app.main:app --host 0.0.0.0 --port 8000"]
