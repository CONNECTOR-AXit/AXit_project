FROM ghcr.io/astral-sh/uv:0.11.29 AS uv

FROM python:3.12.11-slim-bookworm

COPY --from=uv /uv /uvx /bin/

ENV PATH="/workspace/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

RUN groupadd --gid 10001 axit \
    && useradd --uid 10001 --gid axit --no-create-home --shell /usr/sbin/nologin axit \
    && install -d -o axit -g axit -m 0700 /var/lib/axit/blobs

WORKDIR /workspace

COPY pyproject.toml uv.lock alembic.ini ./
RUN uv sync --locked --no-default-groups --no-install-project

COPY apps/api ./apps/api
# Phase 3 MockProvider fixtures are deterministic development artifacts.  They
# stay inside the local image and are never fetched from an external provider.
COPY provider_fixtures ./provider_fixtures

USER axit:axit
WORKDIR /workspace/apps/api

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
