# -- Stage 1: Build UI --
FROM node:22-slim AS ui-builder
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

# -- Stage 2: Python runtime --
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

COPY uv.lock /app/uv.lock
COPY pyproject.toml /app/pyproject.toml

RUN uv sync --frozen --no-install-project

COPY . /app

# Copy built UI into the image
COPY --from=ui-builder /ui/dist /app/ui/dist

RUN uv sync --frozen

ENTRYPOINT ["uv", "run", "netherbrain"]
CMD ["agent"]
