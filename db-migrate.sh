#!/usr/bin/env bash
#
# Generate an Alembic migration using a temporary PostgreSQL container.
#
# Workflow:
#   1. Start a disposable PostgreSQL container
#   2. Apply all existing migrations (upgrade head)
#   3. Autogenerate a new migration from model diff
#   4. Tear down the container
#
# This is completely isolated from the dev environment.
#
# Usage:
#   ./dev/db-regenerate.sh "add foo column"
#   make db-migrate MSG="add foo column"
#
# To reset all migrations and start fresh:
#   rm netherbrain/agent_runtime/alembic/versions/*.py
#   ./dev/db-regenerate.sh "initial schema"
#
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <migration-message>"
    echo ""
    echo "Examples:"
    echo "  $0 \"add foo column\"        # incremental migration"
    echo "  $0 \"initial schema\"        # after clearing versions/"
    exit 1
fi

MESSAGE="$1"
CONTAINER_NAME="netherbrain-migrate-tmp-$$"
PG_USER="migrate"
PG_PASS="migrate"
PG_DB="migrate"

cleanup() {
    echo "Cleaning up temporary container..."
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# -- 1. Start temporary PostgreSQL -------------------------------------------
echo "Starting temporary PostgreSQL container..."
docker run -d \
    --name "$CONTAINER_NAME" \
    -e POSTGRES_USER="$PG_USER" \
    -e POSTGRES_PASSWORD="$PG_PASS" \
    -e POSTGRES_DB="$PG_DB" \
    -p 0:5432 \
    postgres:17 \
    >/dev/null

# Resolve the actual host port assigned by Docker
ACTUAL_PORT=$(docker port "$CONTAINER_NAME" 5432 | head -1 | cut -d: -f2)
DATABASE_URL="postgresql+psycopg://${PG_USER}:${PG_PASS}@localhost:${ACTUAL_PORT}/${PG_DB}"

echo "Temporary database: localhost:${ACTUAL_PORT}"

# Wait for PostgreSQL to accept connections
echo "Waiting for PostgreSQL to be ready..."
for i in $(seq 1 30); do
    if docker exec "$CONTAINER_NAME" pg_isready -U "$PG_USER" >/dev/null 2>&1; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: PostgreSQL did not become ready in time."
        exit 1
    fi
    sleep 0.5
done
echo "PostgreSQL is ready."

# -- 2. Apply existing migrations --------------------------------------------
echo "Applying existing migrations (upgrade head)..."
NETHER_DATABASE_URL="$DATABASE_URL" uv run netherbrain db upgrade

# -- 3. Generate new migration -----------------------------------------------
echo "Generating migration: ${MESSAGE}..."
NETHER_DATABASE_URL="$DATABASE_URL" uv run netherbrain db migrate "$MESSAGE"

echo ""
echo "Done."
