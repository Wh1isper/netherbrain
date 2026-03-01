#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.dev.yml"
PROJECT_NAME="netherbrain-dev"

usage() {
    echo "Usage: $0 {up|down|status|reset}"
    echo ""
    echo "Commands:"
    echo "  up      Start PostgreSQL and Redis containers"
    echo "  down    Stop and remove containers (data volumes preserved)"
    echo "  status  Show container status"
    echo "  reset   Stop containers and remove all data volumes"
    exit 1
}

cmd_up() {
    echo "Starting dev infrastructure..."
    docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" up -d
    echo ""
    echo "Waiting for services to be healthy..."
    docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" up -d --wait
    echo ""
    echo "Dev infrastructure is ready:"
    echo "  PostgreSQL: postgresql://netherbrain:netherbrain@localhost:15432/netherbrain"
    echo "  Redis:      redis://localhost:16379/0"
    echo ""
    echo "Load env vars into your shell:"
    echo "  set -a && source dev/dev.env && set +a"
}

cmd_down() {
    echo "Stopping dev infrastructure..."
    docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" down
    echo "Containers stopped. Data volumes preserved."
}

cmd_status() {
    docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" ps
}

cmd_reset() {
    echo "Stopping dev infrastructure and removing volumes..."
    docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME" down -v
    echo "All containers and data volumes removed."
}

case "${1:-}" in
    up)     cmd_up ;;
    down)   cmd_down ;;
    status) cmd_status ;;
    reset)  cmd_reset ;;
    *)      usage ;;
esac
