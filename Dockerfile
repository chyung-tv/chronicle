# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
ENV PLAYOUT_API_ORIGIN=http://127.0.0.1:8765
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY pyproject.toml README.md ./
COPY playout ./playout
COPY scenarios ./scenarios
RUN pip install --no-cache-dir -e .
COPY --from=web /web /web
COPY start.sh /start.sh
RUN chmod +x /start.sh
ENV PYTHONUNBUFFERED=1
ENV PLAYOUT_API_ORIGIN=http://127.0.0.1:8765
ENV PLAYOUT_API_PORT=8765
ENV PLAYOUT_HOST=127.0.0.1
CMD ["/start.sh"]
