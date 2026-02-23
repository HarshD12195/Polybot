FROM python:3.11-slim as builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir hatchling && \
    pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels .

FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /app/wheels /wheels
COPY pyproject.toml .
RUN pip install --no-cache-dir /wheels/*

COPY . .

# Environment variables for default configuration
ENV PAPER_MODE=true \
    LOG_LEVEL=INFO \
    API_HOST=0.0.0.0 \
    API_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "polymarket_bot", "live"]
