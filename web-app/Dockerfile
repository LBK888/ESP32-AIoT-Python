FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AQUARIUM_HOST=0.0.0.0 \
    AQUARIUM_PORT=8000 \
    AQUARIUM_DATA_DIR=/app/data

WORKDIR /app

COPY requirements.txt pyproject.toml README.md ./
COPY aquarium_app ./aquarium_app
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 aquarium \
    && mkdir -p /app/data \
    && chown -R aquarium:aquarium /app

USER aquarium
EXPOSE 8000
VOLUME ["/app/data"]

CMD ["python", "-m", "aquarium_app", "serve"]

