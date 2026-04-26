FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
COPY requirements-dev.txt /app/requirements-dev.txt

ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ]; then \
        pip install --no-cache-dir -r /app/requirements-dev.txt; \
    else \
        pip install --no-cache-dir -r /app/requirements.txt; \
    fi

COPY src /app/src

CMD ["python", "-u", "src/main.py"]
