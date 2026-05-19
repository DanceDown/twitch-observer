FROM python:3.13-slim AS runtime-wheels

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /build

COPY requirements.txt /build/requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels/runtime -r /build/requirements.txt

FROM python:3.13-slim AS dev-wheels

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /build

COPY requirements.txt /build/requirements.txt
COPY requirements-dev.txt /build/requirements-dev.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels/dev -r /build/requirements-dev.txt

FROM python:3.13-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY requirements.txt /app/requirements.txt
COPY requirements-dev.txt /app/requirements-dev.txt
COPY --from=runtime-wheels /wheels/runtime /tmp/wheels/runtime
COPY --from=dev-wheels /wheels/dev /tmp/wheels/dev

ARG INSTALL_DEV=false
RUN python -m venv /opt/venv \
    && if [ "$INSTALL_DEV" = "true" ]; then \
        /opt/venv/bin/pip install --no-cache-dir --no-index --find-links=/tmp/wheels/dev -r /app/requirements-dev.txt; \
    else \
        /opt/venv/bin/pip install --no-cache-dir --no-index --find-links=/tmp/wheels/runtime -r /app/requirements.txt; \
        /opt/venv/bin/pip uninstall -y ruff >/dev/null 2>&1 || true; \
    fi \
    && rm -rf /tmp/wheels /root/.cache/pip

COPY src /app/src

CMD ["python", "-u", "src/main.py"]
