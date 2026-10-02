FROM golang:1.26-alpine AS schedule-builder

WORKDIR /src/schedule
COPY schedule/go.mod schedule/go.sum ./
COPY schedule/main.go schedule/parser.go schedule/request.go ./
RUN go mod download && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/schedule-bot .

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --upgrade pip && pip install .
COPY --from=schedule-builder /out/schedule-bot /usr/local/bin/schedule-bot
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

CMD ["./docker-entrypoint.sh"]
